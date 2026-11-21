package registry

import (
	"path/filepath"
	"reflect"
	"testing"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"

	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
	lightsailconfig "github.com/mhsanaei/3x-ui/v3/internal/lightsail"
)

func newRegistryTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	db, err := gorm.Open(sqlite.Open(filepath.Join(t.TempDir(), "registry.db")), &gorm.Config{Logger: logger.Discard})
	if err != nil {
		t.Fatalf("open isolated sqlite: %v", err)
	}
	if err := db.AutoMigrate(&model.Node{}, &model.Inbound{}, &model.ClientRecord{}, &model.ClientInbound{}, &model.LightsailManagedNode{}, &model.LightsailInboundReplica{}, &model.LightsailCleanupIntent{}); err != nil {
		t.Fatalf("migrate isolated sqlite: %v", err)
	}
	return db
}

func TestBeginCleanupSnapshotsManagedNodeInboundAndSharedClientIDs(t *testing.T) {
	db := newRegistryTestDB(t)
	store := New(db)
	node := model.Node{Name: "managed-1", Address: "192.0.2.10", Port: 2053, ApiToken: "test-token"}
	if err := db.Create(&node).Error; err != nil {
		t.Fatal(err)
	}
	managed := model.LightsailManagedNode{AccountID: "123456789012", ProfileName: "pool-profile", Region: "us-east-1", InstanceName: "xray-node-1", NodeID: node.Id}
	if err := store.registerNode(&managed, testOwnershipProof(managed)); err != nil {
		t.Fatal(err)
	}
	markNodeReady(t, db, managed.Id)
	inbounds := []model.Inbound{{UserId: 1, Remark: "source-a", Enable: true, Port: 443, Tag: "in-a", NodeID: intPtr(node.Id)}, {UserId: 1, Remark: "source-b", Enable: true, Port: 8443, Tag: "in-b", NodeID: intPtr(node.Id)}}
	if err := db.Create(&inbounds).Error; err != nil {
		t.Fatal(err)
	}
	clients := []model.ClientRecord{{Email: "shared@example.test"}, {Email: "second@example.test"}}
	if err := db.Create(&clients).Error; err != nil {
		t.Fatal(err)
	}
	links := []model.ClientInbound{{ClientId: clients[0].Id, InboundId: inbounds[0].Id}, {ClientId: clients[0].Id, InboundId: inbounds[1].Id}, {ClientId: clients[1].Id, InboundId: inbounds[1].Id}}
	if err := db.Create(&links).Error; err != nil {
		t.Fatal(err)
	}

	intent, err := store.BeginCleanup(CleanupRequest{
		IdempotencyKey: "delete-12345678", AccountID: managed.AccountID, ProfileName: managed.ProfileName, Region: managed.Region, InstanceName: managed.InstanceName,
	})
	if err != nil {
		t.Fatal(err)
	}
	if intent.Phase != CleanupPrepared || intent.NodeID != node.Id {
		t.Fatalf("cleanup intent identity/phase = %#v", intent)
	}
	if !reflect.DeepEqual(intent.InboundIDs, []int{inbounds[0].Id, inbounds[1].Id}) {
		t.Fatalf("inbound snapshot = %v", intent.InboundIDs)
	}
	if !reflect.DeepEqual(intent.ClientIDs, []int{clients[0].Id, clients[1].Id}) {
		t.Fatalf("client snapshot = %v", intent.ClientIDs)
	}

	if err := db.Where("id = ?", inbounds[0].Id).Delete(&model.Inbound{}).Error; err != nil {
		t.Fatal(err)
	}
	retry, err := store.BeginCleanup(CleanupRequest{
		IdempotencyKey: "delete-12345678", AccountID: managed.AccountID, ProfileName: managed.ProfileName, Region: managed.Region, InstanceName: managed.InstanceName,
	})
	if err != nil {
		t.Fatal(err)
	}
	if retry.Id != intent.Id || !reflect.DeepEqual(retry.InboundIDs, intent.InboundIDs) || !reflect.DeepEqual(retry.ClientIDs, intent.ClientIDs) {
		t.Fatalf("retry changed durable cleanup snapshot: first=%#v retry=%#v", intent, retry)
	}
}

func TestBeginCleanupRejectsUnmanagedOrMismatchedInstance(t *testing.T) {
	db := newRegistryTestDB(t)
	store := New(db)
	_, err := store.BeginCleanup(CleanupRequest{IdempotencyKey: "delete-12345678", AccountID: "123456789012", ProfileName: "pool-profile", Region: "us-east-1", InstanceName: "manual-instance"})
	if err == nil {
		t.Fatal("cleanup intent accepted for an instance without a project ownership mapping")
	}
}

func TestInboundReplicaMappingIsStableAndUniquePerSourceAndNode(t *testing.T) {
	db := newRegistryTestDB(t)
	store := New(db)
	node := model.Node{Name: "managed-3", Address: "192.0.2.12", Port: 2053, ApiToken: "test-token"}
	if err := db.Create(&node).Error; err != nil {
		t.Fatal(err)
	}
	managed := model.LightsailManagedNode{AccountID: "123456789012", ProfileName: "pool-profile", Region: "us-east-1", InstanceName: "xray-node-3", NodeID: node.Id}
	if err := store.registerNode(&managed, testOwnershipProof(managed)); err != nil {
		t.Fatal(err)
	}
	markNodeReady(t, db, managed.Id)
	source := model.Inbound{UserId: 1, Remark: "master", Enable: true, Port: 443, Tag: "master-tag"}
	target := model.Inbound{UserId: 1, Remark: "replica", Enable: true, Port: 443, Tag: "replica-tag", NodeID: intPtr(node.Id)}
	if err := db.Create(&source).Error; err != nil {
		t.Fatal(err)
	}
	if err := db.Create(&target).Error; err != nil {
		t.Fatal(err)
	}
	first := InboundReplica{SourceInboundID: source.Id, NodeID: node.Id, ReplicaInboundID: target.Id}
	if err := store.registerInboundReplica(first); err != nil {
		t.Fatal(err)
	}
	if err := store.registerInboundReplica(first); err == nil {
		t.Fatal("duplicate source/node mapping was accepted")
	}
	got, err := store.listInboundReplicas(node.Id)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(got, []InboundReplica{first}) {
		t.Fatalf("replica mappings = %#v", got)
	}
}

func TestCleanupIntentTransitionsAreMonotonicAndIdempotent(t *testing.T) {
	db := newRegistryTestDB(t)
	store := New(db)
	node := model.Node{Name: "managed-2", Address: "192.0.2.11", Port: 2053, ApiToken: "test-token"}
	if err := db.Create(&node).Error; err != nil {
		t.Fatal(err)
	}
	managed := model.LightsailManagedNode{AccountID: "123456789012", ProfileName: "pool-profile", Region: "us-east-1", InstanceName: "xray-node-2", NodeID: node.Id}
	if err := store.registerNode(&managed, testOwnershipProof(managed)); err != nil {
		t.Fatal(err)
	}
	markNodeReady(t, db, managed.Id)
	intent, err := store.BeginCleanup(CleanupRequest{IdempotencyKey: "delete-abcdefgh", AccountID: managed.AccountID, ProfileName: managed.ProfileName, Region: managed.Region, InstanceName: managed.InstanceName})
	if err != nil {
		t.Fatal(err)
	}
	if err := store.advanceCleanup(intent.Id, CleanupPanelCleaned); err == nil {
		t.Fatal("cleanup intent skipped the instance-deleted phase")
	}
	for _, phase := range []string{CleanupInstanceDeleted, CleanupPanelCleaned, CleanupComplete} {
		if err := store.advanceCleanup(intent.Id, phase); err != nil {
			t.Fatalf("advance to %s: %v", phase, err)
		}
		if err := store.advanceCleanup(intent.Id, phase); err != nil {
			t.Fatalf("repeat %s: %v", phase, err)
		}
	}
	if err := store.advanceCleanup(intent.Id, CleanupPrepared); err == nil {
		t.Fatal("cleanup intent moved backwards")
	}
	var got model.LightsailCleanupIntent
	if err := db.First(&got, intent.Id).Error; err != nil {
		t.Fatal(err)
	}
	if got.Phase != CleanupComplete {
		t.Fatalf("persisted cleanup phase = %q", got.Phase)
	}
	pending, err := store.ListPendingCleanup(10)
	if err != nil {
		t.Fatal(err)
	}
	if len(pending) != 0 {
		t.Fatalf("completed intent remained pending: %#v", pending)
	}
}

func intPtr(value int) *int { return &value }

func testOwnershipProof(managed model.LightsailManagedNode) ownershipProof {
	return ownershipProof{AccountID: managed.AccountID, ProfileName: managed.ProfileName, Region: managed.Region, InstanceName: managed.InstanceName, Tags: map[string]string{
		lightsailconfig.ManagedByTag:   lightsailconfig.ManagedByValue,
		lightsailconfig.ProjectTag:     lightsailconfig.ProjectValue,
		lightsailconfig.AccountIDTag:   managed.AccountID,
		lightsailconfig.ProfileNameTag: managed.ProfileName,
	}}
}

func markNodeReady(t *testing.T, db *gorm.DB, id int) {
	t.Helper()
	if err := db.Model(&model.LightsailManagedNode{}).Where("id = ?", id).Update("state", ManagedNodeReady).Error; err != nil {
		t.Fatalf("set fixture node ready: %v", err)
	}
}
