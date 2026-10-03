package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strings"
	"time"
)

const pauseAnnotation = "backup.jetersen.dev/forgejo-pause"

type deployment struct {
	Metadata struct {
		ResourceVersion string            `json:"resourceVersion"`
		Annotations     map[string]string `json:"annotations"`
	} `json:"metadata"`
	Spec struct {
		Replicas int `json:"replicas"`
		Selector struct {
			MatchLabels map[string]string `json:"matchLabels"`
		} `json:"selector"`
	} `json:"spec"`
	Status struct {
		AvailableReplicas int `json:"availableReplicas"`
	} `json:"status"`
}

type forgejoAPI interface {
	Deployment(context.Context) (deployment, error)
	Patch(context.Context, deployment, int, *string) error
	Pods(context.Context, deployment) (int, error)
}

type kubernetes struct {
	client                 *http.Client
	base, namespace, token string
}

func newKubernetes() (*kubernetes, error) {
	const root = "/var/run/secrets/kubernetes.io/serviceaccount/"
	namespace, err := os.ReadFile(root + "namespace")
	if err != nil {
		return nil, err
	}
	token, err := os.ReadFile(root + "token")
	if err != nil {
		return nil, err
	}
	ca, err := os.ReadFile(root + "ca.crt")
	if err != nil {
		return nil, err
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(ca) {
		return nil, backupError("Invalid Kubernetes CA certificate.")
	}
	return &kubernetes{&http.Client{Timeout: 30 * time.Second,
		Transport:     &http.Transport{TLSClientConfig: &tls.Config{RootCAs: pool, MinVersion: tls.VersionTLS12}},
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }},
		"https://kubernetes.default.svc", strings.TrimSpace(string(namespace)), strings.TrimSpace(string(token))}, nil
}

func (k *kubernetes) request(ctx context.Context, method, resource string, query url.Values, payload, output any) error {
	group := "apis/apps/v1"
	if resource == "pods" {
		group = "api/v1"
	}
	var body []byte
	if payload != nil {
		var err error
		body, err = json.Marshal(payload)
		if err != nil {
			return err
		}
	}
	endpoint := k.base + "/" + group + "/namespaces/" + url.PathEscape(k.namespace) + "/" + resource
	if len(query) > 0 {
		endpoint += "?" + query.Encode()
	}
	req, err := http.NewRequestWithContext(ctx, method, endpoint, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+k.token)
	req.Header.Set("Content-Type", "application/merge-patch+json")
	response, err := k.client.Do(req)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return backupError(fmt.Sprintf("Kubernetes request failed with HTTP %d.", response.StatusCode))
	}
	if output == nil {
		return nil
	}
	return json.NewDecoder(io.LimitReader(response.Body, 8<<20)).Decode(output)
}

func (k *kubernetes) Deployment(ctx context.Context) (deployment, error) {
	var result deployment
	err := k.request(ctx, "GET", "deployments/forgejo", nil, nil, &result)
	return result, err
}

func (k *kubernetes) Patch(ctx context.Context, current deployment, replicas int, marker *string) error {
	return k.request(ctx, "PATCH", "deployments/forgejo", nil, map[string]any{
		"metadata": map[string]any{"resourceVersion": current.Metadata.ResourceVersion, "annotations": map[string]any{pauseAnnotation: marker}},
		"spec":     map[string]int{"replicas": replicas}}, nil)
}

func (k *kubernetes) Pods(ctx context.Context, current deployment) (int, error) {
	labels := make([]string, 0, len(current.Spec.Selector.MatchLabels))
	for key, value := range current.Spec.Selector.MatchLabels {
		labels = append(labels, key+"="+value)
	}
	if len(labels) == 0 {
		return 0, backupError("Forgejo deployment has no pod selector.")
	}
	sort.Strings(labels)
	var result struct {
		Items []json.RawMessage `json:"items"`
	}
	err := k.request(ctx, "GET", "pods", url.Values{"labelSelector": {strings.Join(labels, ",")}}, nil, &result)
	return len(result.Items), err
}
