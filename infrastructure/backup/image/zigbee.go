package main

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/url"
	"os"
	"sort"
	"strings"
	"time"

	mqtt "github.com/eclipse/paho.mqtt.golang"
)

func environment() map[string]string {
	result := map[string]string{}
	for _, entry := range os.Environ() {
		key, value, _ := strings.Cut(entry, "=")
		result[key] = value
	}
	return result
}

func prepareZigbee(data []byte, overrides map[string]string) ([]byte, error) {
	archive, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return nil, err
	}
	files := map[string][]byte{}
	seen := map[string]bool{}
	var size uint64
	for _, entry := range archive.File {
		name := entry.Name
		if strings.HasPrefix(name, "/") || strings.Contains(name, "\\") || contains(strings.Split(name, "/"), "..") || seen[name] {
			return nil, backupError("Unsafe archive path.")
		}
		seen[name] = true
		if strings.HasPrefix(name, "log/") || strings.HasPrefix(name, "ota/") || strings.HasSuffix(name, ".log") || strings.HasSuffix(name, ".tmp") || entry.FileInfo().IsDir() {
			continue
		}
		if entry.UncompressedSize64 > 64<<20 {
			return nil, backupError("Zigbee archive exceeds its size limit.")
		}
		size += entry.UncompressedSize64
		if size > 64<<20 {
			return nil, backupError("Zigbee archive exceeds its size limit.")
		}
		reader, err := entry.Open()
		if err != nil {
			return nil, err
		}
		files[name], err = io.ReadAll(io.LimitReader(reader, 64<<20+1))
		reader.Close()
		if err != nil {
			return nil, err
		}
	}
	for _, name := range []string{"configuration.yaml", "database.db", "coordinator_backup.json", "state.json"} {
		if len(files[name]) == 0 {
			return nil, backupError("Missing Zigbee recovery data.")
		}
	}
	var coordinator struct {
		Metadata struct {
			Format string `json:"format"`
		} `json:"metadata"`
		NetworkKey struct {
			Key json.RawMessage `json:"key"`
		} `json:"network_key"`
		PanID         json.RawMessage `json:"pan_id"`
		ExtendedPanID json.RawMessage `json:"extended_pan_id"`
	}
	if json.Unmarshal(files["coordinator_backup.json"], &coordinator) != nil || coordinator.Metadata.Format != "zigpy/open-coordinator-backup" || emptyJSON(coordinator.NetworkKey.Key) || emptyJSON(coordinator.PanID) || emptyJSON(coordinator.ExtendedPanID) {
		return nil, backupError("Incomplete coordinator backup.")
	}
	if !json.Valid(files["state.json"]) {
		return nil, backupError("Invalid Zigbee state.")
	}
	for _, line := range bytes.Split(files["database.db"], []byte("\n")) {
		if len(bytes.TrimSpace(line)) > 0 && !json.Valid(line) {
			return nil, backupError("Invalid Zigbee device database.")
		}
	}
	files["deployment-environment.json"], err = json.Marshal(overrides)
	if err != nil {
		return nil, err
	}
	var output bytes.Buffer
	writer := zip.NewWriter(&output)
	names := make([]string, 0, len(files))
	for name := range files {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		entry, err := writer.Create(name)
		if err != nil {
			return nil, err
		}
		if _, err := entry.Write(files[name]); err != nil {
			return nil, err
		}
	}
	if err := writer.Close(); err != nil {
		return nil, err
	}
	return output.Bytes(), nil
}

func contains(values []string, value string) bool {
	for _, v := range values {
		if v == value {
			return true
		}
	}
	return false
}
func emptyJSON(value json.RawMessage) bool {
	return len(value) == 0 || string(value) == "null" || string(value) == `""` || string(value) == "[]"
}

func zigbeeResponse(payload []byte, retained bool, transaction string) ([]byte, bool, error) {
	if retained {
		return nil, false, nil
	}
	var response struct {
		Transaction, Status string
		Data                struct{ Zip string }
	}
	if len(payload) > 33<<20 || json.Unmarshal(payload, &response) != nil {
		return nil, true, backupError("Invalid Zigbee backup response.")
	}
	if response.Transaction != transaction {
		return nil, false, nil
	}
	if response.Status != "ok" || response.Data.Zip == "" || len(response.Data.Zip) > 32<<20 {
		return nil, true, backupError("Native Zigbee backup failed.")
	}
	archive, err := base64.StdEncoding.Strict().DecodeString(response.Data.Zip)
	if err != nil {
		return nil, true, backupError("Invalid Zigbee archive response.")
	}
	return archive, true, nil
}

func exportZigbee(ctx context.Context, env map[string]string, target string) error {
	overrides := map[string]string{}
	for key, value := range env {
		if strings.HasPrefix(key, "ZIGBEE2MQTT_CONFIG_") {
			overrides[key] = value
		}
	}
	for _, name := range []string{"MQTT_USER", "MQTT_PASSWORD", "ADVANCED_NETWORK_KEY", "ADVANCED_PAN_ID", "ADVANCED_EXT_PAN_ID"} {
		if overrides["ZIGBEE2MQTT_CONFIG_"+name] == "" {
			return backupError("Missing Zigbee recovery environment.")
		}
	}
	broker, err := url.Parse(env["MQTT_SERVER"])
	if err != nil || broker.Host == "" || broker.User != nil {
		return backupError("Invalid MQTT server.")
	}
	switch broker.Scheme {
	case "mqtt":
		broker.Scheme = "tcp"
	case "mqtts":
		broker.Scheme = "ssl"
	default:
		return backupError("Unsupported MQTT transport.")
	}
	transaction := randomID()
	topic := "zigbee2mqtt/bridge/response/backup"
	type result struct {
		archive []byte
		err     error
	}
	results := make(chan result, 1)
	finish := func(value result) {
		select {
		case results <- value:
		default:
		}
	}
	options := mqtt.NewClientOptions().AddBroker(broker.String()).SetClientID("backup-export-" + transaction).
		SetUsername(overrides["ZIGBEE2MQTT_CONFIG_MQTT_USER"]).SetPassword(overrides["ZIGBEE2MQTT_CONFIG_MQTT_PASSWORD"]).
		SetAutoReconnect(false).SetConnectRetry(false).SetCleanSession(true).SetOrderMatters(false).
		SetConnectTimeout(15 * time.Second).SetWriteTimeout(15 * time.Second).
		SetConnectionLostHandler(func(mqtt.Client, error) { finish(result{err: backupError("MQTT connection failed.")}) })
	client := mqtt.NewClient(options)
	defer client.Disconnect(250)
	if token := client.Connect(); !token.WaitTimeout(15*time.Second) || token.Error() != nil {
		return backupError("MQTT connection failed.")
	}
	subscription := client.Subscribe(topic, 1, func(_ mqtt.Client, message mqtt.Message) {
		if message.Topic() != topic {
			return
		}
		archive, matched, err := zigbeeResponse(message.Payload(), message.Retained(), transaction)
		if matched {
			finish(result{archive, err})
		}
	})
	if !subscription.WaitTimeout(15*time.Second) || subscription.Error() != nil {
		return backupError("MQTT subscription failed.")
	}
	granted := subscription.(*mqtt.SubscribeToken).Result()
	if qos, ok := granted[topic]; !ok || qos > 1 {
		return backupError("MQTT subscription failed.")
	}
	request, _ := json.Marshal(map[string]string{"transaction": transaction})
	if token := client.Publish("zigbee2mqtt/bridge/request/backup", 1, false, request); !token.WaitTimeout(15*time.Second) || token.Error() != nil {
		return backupError("MQTT publish failed.")
	}
	ctx, cancel := context.WithTimeout(ctx, 3*time.Minute)
	defer cancel()
	var received result
	select {
	case <-ctx.Done():
		return backupError("Backup request timed out or interrupted.")
	case received = <-results:
	}
	if received.err != nil {
		return received.err
	}
	archive, err := prepareZigbee(received.archive, overrides)
	if err != nil {
		return err
	}
	if err := atomicExport(ctx, target, func(f *os.File) error { _, err := f.Write(archive); return err }, nil); err != nil {
		return err
	}
	fmt.Println("Validated Zigbee recovery export staged.")
	return nil
}
