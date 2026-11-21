package database

import (
	"testing"

	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
)

func TestAllModelsIncludeLightsailOwnershipAndCleanupTables(t *testing.T) {
	want := map[string]bool{
		"lightsail_managed_nodes":    false,
		"lightsail_inbound_replicas": false,
		"lightsail_cleanup_intents":  false,
	}
	for _, mdl := range allModels() {
		switch mdl.(type) {
		case *model.LightsailManagedNode:
			want["lightsail_managed_nodes"] = true
		case *model.LightsailInboundReplica:
			want["lightsail_inbound_replicas"] = true
		case *model.LightsailCleanupIntent:
			want["lightsail_cleanup_intents"] = true
		}
	}
	for table, included := range want {
		if !included {
			t.Errorf("allModels omits Lightsail table %s", table)
		}
	}
}
