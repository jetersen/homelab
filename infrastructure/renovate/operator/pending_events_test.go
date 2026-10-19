package utils

import (
 "testing"
 api "renovate-operator/api/v1alpha1"
 "renovate-operator/internal/types"
)

func TestPendingEventSurvivesRun(t *testing.T) {
 for _, terminal := range []api.RenovateProjectStatus{api.JobStatusCompleted, api.JobStatusFailed} {
  t.Run(string(terminal), func(t *testing.T) {
   state := &api.RenovateProjectState{Status: api.JobStatusRunning}
   for range 3 {
    GetUpdateStatusForProject(state, &types.RenovateStatusUpdate{Status: api.JobStatusScheduled, Priority: 1})
   }
   if state.Status != api.JobStatusRunning || state.Priority != 1 { t.Fatalf("event interrupted running job: %+v", state) }
   GetUpdateStatusForProject(state, &types.RenovateStatusUpdate{Status: terminal})
   if state.Status != api.JobStatusScheduled { t.Fatalf("follow-up event lost: %+v", state) }
   GetUpdateStatusForProject(state, &types.RenovateStatusUpdate{Status: api.JobStatusRunning})
   if state.Priority != 0 { t.Fatal("pending request was not consumed") }
   GetUpdateStatusForProject(state, &types.RenovateStatusUpdate{Status: terminal})
   if state.Status != terminal { t.Fatal("job reran without another event") }
  })
 }
}
