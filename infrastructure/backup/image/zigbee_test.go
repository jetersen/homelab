package main

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/eclipse/paho.mqtt.golang/packets"
)

func zigbeeFixture() map[string][]byte {
	return map[string][]byte{
		"configuration.yaml": []byte("version: 4"), "database.db": []byte("{\"id\":1}\n{\"id\":2}\n"),
		"coordinator_backup.json": []byte(`{"metadata":{"format":"zigpy/open-coordinator-backup"},"network_key":{"key":"fixture"},"pan_id":"fixture","extended_pan_id":"fixture"}`),
		"state.json":              []byte(`{"device":{"state":"ON"}}`), "configuration_backup_v4.yaml": []byte("version: 4"),
		"external_converters/example.js": []byte("module.exports = {};"), "log/today/log.log": []byte("log"), "ota/firmware.bin": []byte("firmware"), "unfinished.tmp": []byte("partial"), "migration.log": []byte("log"),
	}
}

func unzipFixture(t *testing.T, data []byte) map[string][]byte {
	t.Helper()
	reader, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		t.Fatal(err)
	}
	files := map[string][]byte{}
	for _, entry := range reader.File {
		r, err := entry.Open()
		if err != nil {
			t.Fatal(err)
		}
		files[entry.Name], err = io.ReadAll(r)
		r.Close()
		if err != nil {
			t.Fatal(err)
		}
	}
	return files
}

func TestZigbeeArchive(t *testing.T) {
	overrides := map[string]string{"ZIGBEE2MQTT_CONFIG_ADVANCED_NETWORK_KEY": "fixture"}
	data, err := prepareZigbee(zipFixture(t, zigbeeFixture()), overrides)
	if err != nil {
		t.Fatal(err)
	}
	files := unzipFixture(t, data)
	if len(files) != 7 || files["external_converters/example.js"] == nil || files["configuration_backup_v4.yaml"] == nil || files["log/today/log.log"] != nil || files["ota/firmware.bin"] != nil {
		t.Fatal("Recovery file selection changed")
	}
	var saved map[string]string
	if err := json.Unmarshal(files["deployment-environment.json"], &saved); err != nil || saved["ZIGBEE2MQTT_CONFIG_ADVANCED_NETWORK_KEY"] != "fixture" {
		t.Fatal("Recovery overrides missing")
	}
	for _, scenario := range []string{"missing database", "invalid database", "invalid coordinator", "unsafe path", "invalid state"} {
		t.Run(scenario, func(t *testing.T) {
			files := zigbeeFixture()
			switch scenario {
			case "missing database":
				delete(files, "database.db")
			case "invalid database":
				files["database.db"] = []byte("broken")
			case "invalid coordinator":
				files["coordinator_backup.json"] = []byte("{}")
			case "unsafe path":
				files["../outside"] = []byte("invalid")
			case "invalid state":
				files["state.json"] = []byte("invalid")
			}
			if _, err := prepareZigbee(zipFixture(t, files), nil); err == nil {
				t.Fatal("Invalid recovery archive accepted")
			}
		})
	}
}

func TestZigbeeIgnoresRetainedAndUnrelatedResponses(t *testing.T) {
	payload := []byte(`{"transaction":"fixture","status":"ok","data":{"zip":"Zml4dHVyZQ=="}}`)
	if _, matched, err := zigbeeResponse(payload, true, "fixture"); matched || err != nil {
		t.Fatal("Retained response accepted")
	}
	if _, matched, err := zigbeeResponse(payload, false, "another"); matched || err != nil {
		t.Fatal("Unrelated transaction accepted")
	}
	if data, matched, err := zigbeeResponse(payload, false, "fixture"); !matched || err != nil || string(data) != "fixture" {
		t.Fatal("Matching response rejected")
	}
	if _, matched, err := zigbeeResponse([]byte(`{"transaction":"fixture","status":"ok","data":{"zip":"%%%"}}`), false, "fixture"); !matched || err == nil {
		t.Fatal("Invalid archive accepted")
	}
}

func TestZigbeeMQTTExport(t *testing.T) {
	for _, reject := range []bool{false, true} {
		t.Run(fmt.Sprintf("subscription-rejected=%t", reject), func(t *testing.T) {
			archive := zipFixture(t, zigbeeFixture())
			listener, err := net.Listen("tcp", "127.0.0.1:0")
			if err != nil {
				t.Fatal(err)
			}
			defer listener.Close()
			finished := make(chan error, 1)
			go func() {
				finished <- func() error {
					connection, err := listener.Accept()
					if err != nil {
						return err
					}
					defer connection.Close()
					connection.SetDeadline(time.Now().Add(5 * time.Second))
					packet, err := packets.ReadPacket(connection)
					if err != nil {
						return err
					}
					connect, ok := packet.(*packets.ConnectPacket)
					if !ok || connect.Username != "fixture-user" || string(connect.Password) != "fixture-password" || !strings.HasPrefix(connect.ClientIdentifier, "backup-export-") || !connect.CleanSession {
						return fmt.Errorf("Incorrect client setup")
					}
					ack := packets.NewControlPacket(packets.Connack).(*packets.ConnackPacket)
					if err := ack.Write(connection); err != nil {
						return err
					}
					packet, err = packets.ReadPacket(connection)
					if err != nil {
						return err
					}
					subscribe, ok := packet.(*packets.SubscribePacket)
					if !ok || len(subscribe.Topics) != 1 || subscribe.Topics[0] != "zigbee2mqtt/bridge/response/backup" {
						return fmt.Errorf("Incorrect subscription")
					}
					suback := packets.NewControlPacket(packets.Suback).(*packets.SubackPacket)
					suback.MessageID = subscribe.MessageID
					suback.ReturnCodes = []byte{1}
					if reject {
						suback.ReturnCodes = []byte{128}
					}
					if err := suback.Write(connection); err != nil {
						return err
					}
					if reject {
						return nil
					}
					packet, err = packets.ReadPacket(connection)
					if err != nil {
						return err
					}
					publish, ok := packet.(*packets.PublishPacket)
					if !ok || publish.TopicName != "zigbee2mqtt/bridge/request/backup" || publish.Retain || publish.Qos != 1 {
						return fmt.Errorf("Incorrect native backup request")
					}
					puback := packets.NewControlPacket(packets.Puback).(*packets.PubackPacket)
					puback.MessageID = publish.MessageID
					if err := puback.Write(connection); err != nil {
						return err
					}
					var request map[string]string
					if err := json.Unmarshal(publish.Payload, &request); err != nil {
						return err
					}
					for _, response := range []struct {
						transaction string
						retained    bool
					}{{request["transaction"], true}, {"unrelated", false}, {request["transaction"], false}} {
						message := packets.NewControlPacket(packets.Publish).(*packets.PublishPacket)
						message.TopicName = subscribe.Topics[0]
						message.Retain = response.retained
						message.Payload, _ = json.Marshal(map[string]any{"transaction": response.transaction, "status": "ok", "data": map[string]string{"zip": base64.StdEncoding.EncodeToString(archive)}})
						if err := message.Write(connection); err != nil {
							return err
						}
					}
					// Keep the connection open until the client has consumed its response.
					_, err = packets.ReadPacket(connection)
					if err == io.EOF {
						return nil
					}
					return err
				}()
			}()
			env := map[string]string{"MQTT_SERVER": "mqtt://" + listener.Addr().String(), "ZIGBEE2MQTT_CONFIG_MQTT_USER": "fixture-user", "ZIGBEE2MQTT_CONFIG_MQTT_PASSWORD": "fixture-password", "ZIGBEE2MQTT_CONFIG_ADVANCED_NETWORK_KEY": "fixture", "ZIGBEE2MQTT_CONFIG_ADVANCED_PAN_ID": "fixture", "ZIGBEE2MQTT_CONFIG_ADVANCED_EXT_PAN_ID": "fixture"}
			target := filepath.Join(t.TempDir(), "backups/zigbee2mqtt.zip")
			err = exportZigbee(context.Background(), env, target)
			if reject {
				if err == nil {
					t.Fatal("Rejected subscription accepted")
				}
			} else {
				if err != nil {
					t.Fatal(err)
				}
				if unzipFixture(t, readFixture(t, target))["deployment-environment.json"] == nil {
					t.Fatal("Recovery environment not staged")
				}
			}
			if err := <-finished; err != nil {
				t.Fatal(err)
			}
		})
	}
}
