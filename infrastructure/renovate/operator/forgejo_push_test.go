package webhook

import (
	"encoding/json"
	"testing"
)

func TestForgejoDefaultBranchPush(t *testing.T) {
	for _, tc := range []struct {
		name, ref, branch, after string
		deleted, valid           bool
	}{
		{"default branch", "refs/heads/main", "main", "abc123", false, true},
		{"custom default branch", "refs/heads/trunk", "trunk", "abc123", false, true},
		{"Renovate branch", "refs/heads/renovate/example", "main", "abc123", false, false},
		{"tag", "refs/tags/main", "main", "abc123", false, false},
		{"unknown default", "refs/heads/main", "", "abc123", false, false},
		{"missing ref", "", "main", "abc123", false, false},
		{"deleted flag", "refs/heads/main", "main", "abc123", true, false},
		{"deleted SHA", "refs/heads/main", "main", "0000000000000000000000000000000000000000", false, false},
		{"missing SHA", "refs/heads/main", "main", "", false, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			// Decode wire field names so accidental struct-tag changes also fail.
			body, err := json.Marshal(map[string]any{
				"ref": tc.ref, "after": tc.after, "deleted": tc.deleted,
				"repository": map[string]string{"full_name": "owner/repo", "default_branch": tc.branch},
			})
			if err != nil {
				t.Fatal(err)
			}
			var payload ForgejoEvent
			if err := json.Unmarshal(body, &payload); err != nil {
				t.Fatal(err)
			}
			valid, reason := isValidForgejoEvent("push", &payload)
			if valid != tc.valid {
				t.Fatalf("valid = %v, want %v: %s", valid, tc.valid, reason)
			}
		})
	}
}
