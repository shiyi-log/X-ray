package service

import (
	"net/netip"
	"path/filepath"
	"testing"

	"github.com/mhsanaei/3x-ui/v3/internal/database"
	"github.com/mhsanaei/3x-ui/v3/internal/database/dbtest"
	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
	"github.com/mhsanaei/3x-ui/v3/internal/web/runtime"
)

func TestNodeService_UpdateDynamicIPv4OnlyChangesAPIAddressAndInvalidatesRemote(t *testing.T) {
	dbDir := t.TempDir()
	t.Setenv("XUI_DB_FOLDER", dbDir)
	dbtest.InitDB(t, filepath.Join(dbDir, "x-ui.db"))
	db := database.GetDB()

	node := &model.Node{
		Name:              "lightsail-node",
		Scheme:            "https",
		Address:           "192.0.2.10",
		Port:              2096,
		BasePath:          "/panel/",
		Enable:            true,
		TlsVerifyMode:     "pin",
		PinnedCertSha256:  "pinned-fingerprint",
		InboundSyncMode:   "selected",
		InboundTags:       []string{"manual-tag"},
		ConfigDirty:       false,
		ConfigDirtyAt:     123,
		InboundsAdoptedAt: 456,
	}
	if err := db.Create(node).Error; err != nil {
		t.Fatalf("create node: %v", err)
	}

	previousManager := runtime.GetManager()
	manager := runtime.NewManager(runtime.LocalDeps{})
	runtime.SetManager(manager)
	t.Cleanup(func() { runtime.SetManager(previousManager) })

	oldRemote, err := manager.RemoteFor(node)
	if err != nil {
		t.Fatalf("create cached remote: %v", err)
	}
	address := netip.MustParseAddr("198.51.100.25")
	if err := (&NodeService{}).UpdateDynamicIPv4(node.Id, address); err != nil {
		t.Fatalf("UpdateDynamicIPv4: %v", err)
	}

	var got model.Node
	if err := db.First(&got, node.Id).Error; err != nil {
		t.Fatalf("reload node: %v", err)
	}
	if got.Address != address.String() {
		t.Fatalf("Address = %q, want %q", got.Address, address)
	}
	if got.UpdatedAt != node.UpdatedAt {
		t.Fatalf("UpdatedAt changed from %d to %d during an address-only update", node.UpdatedAt, got.UpdatedAt)
	}
	if got.Scheme != node.Scheme || got.Port != node.Port || got.BasePath != node.BasePath || got.ApiToken != node.ApiToken ||
		got.TlsVerifyMode != node.TlsVerifyMode || got.PinnedCertSha256 != node.PinnedCertSha256 ||
		got.InboundSyncMode != node.InboundSyncMode || len(got.InboundTags) != 1 || got.InboundTags[0] != node.InboundTags[0] ||
		got.ConfigDirty != node.ConfigDirty || got.ConfigDirtyAt != node.ConfigDirtyAt || got.InboundsAdoptedAt != node.InboundsAdoptedAt {
		t.Fatalf("API address update changed unrelated node configuration: before=%+v after=%+v", node, got)
	}

	newRemote, err := manager.RemoteFor(&got)
	if err != nil {
		t.Fatalf("recreate remote after address update: %v", err)
	}
	if newRemote == oldRemote {
		t.Fatal("remote connection cache was not invalidated after address update")
	}
}

func TestNodeService_UpdateDynamicIPv4RejectsInvalidAddressAndNodeID(t *testing.T) {
	dbDir := t.TempDir()
	t.Setenv("XUI_DB_FOLDER", dbDir)
	dbtest.InitDB(t, filepath.Join(dbDir, "x-ui.db"))
	if err := (&NodeService{}).UpdateDynamicIPv4(999, netip.MustParseAddr("198.51.100.25")); err == nil {
		t.Fatal("expected update for missing node to be rejected")
	}

	for _, tc := range []struct {
		name    string
		nodeID  int
		address netip.Addr
	}{
		{name: "missing node", nodeID: 0, address: netip.MustParseAddr("198.51.100.25")},
		{name: "IPv6", nodeID: 1, address: netip.MustParseAddr("2001:db8::1")},
		{name: "unspecified IPv4", nodeID: 1, address: netip.IPv4Unspecified()},
		{name: "invalid address", nodeID: 1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if err := (&NodeService{}).UpdateDynamicIPv4(tc.nodeID, tc.address); err == nil {
				t.Fatal("expected invalid Lightsail address update to be rejected")
			}
		})
	}
}
