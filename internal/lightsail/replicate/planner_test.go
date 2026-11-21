package replicate

import (
	"bytes"
	"reflect"
	"testing"
)

func TestPlanReplicationCopiesEveryInboundClientAndProducesNodeScopedTags(t *testing.T) {
	inbounds := []Inbound{
		{ID: 2, Tag: "in-8443-tcp", Config: []byte(`{"protocol":"vless","port":8443}`)},
		{ID: 1, Tag: "in-443-tcp", Config: []byte(`{"protocol":"vless","port":443}`)},
	}
	clients := []Client{
		{ID: 12, Email: "shared@example.test", Config: []byte(`{"uuid":"client-12","enable":true}`)},
		{ID: 11, Email: "second@example.test", Config: []byte(`{"uuid":"client-11","enable":false}`)},
	}
	associations := []ClientAssociation{
		{InboundID: 2, ClientID: 12, FlowOverride: ""},
		{InboundID: 1, ClientID: 12, FlowOverride: "xtls-rprx-vision"},
		{InboundID: 1, ClientID: 11, FlowOverride: ""},
	}

	got, err := PlanReplication(7, inbounds, clients, associations)
	if err != nil {
		t.Fatalf("PlanReplication returned error: %v", err)
	}
	if got.NodeID != 7 || len(got.Inbounds) != 2 {
		t.Fatalf("replication plan = %#v", got)
	}
	wantTags := []string{"n7-in-443-tcp", "n7-in-8443-tcp"}
	for i, replica := range got.Inbounds {
		if replica.TargetNodeID != 7 || replica.ID != 0 || replica.Tag != wantTags[i] {
			t.Fatalf("replica %d = %#v", i, replica)
		}
		source := inbounds[1-i]
		if replica.SourceInboundID != source.ID || !bytes.Equal(replica.Config, source.Config) {
			t.Fatalf("replica %d lost source identity/config: %#v", i, replica)
		}
	}
	if len(got.Inbounds[0].Clients) != 2 || len(got.Inbounds[1].Clients) != 1 {
		t.Fatalf("replica client counts = %d, %d", len(got.Inbounds[0].Clients), len(got.Inbounds[1].Clients))
	}
	if got.Inbounds[0].Clients[0].ClientID != 11 || got.Inbounds[0].Clients[1].ClientID != 12 ||
		got.Inbounds[0].Clients[1].FlowOverride != "xtls-rprx-vision" ||
		!bytes.Equal(got.Inbounds[0].Clients[0].Config, clients[1].Config) ||
		!bytes.Equal(got.Inbounds[0].Clients[1].Config, clients[0].Config) {
		t.Fatalf("replicated clients did not preserve all client settings: %#v", got.Inbounds[0].Clients)
	}
	if got.Inbounds[1].Clients[0].ClientID != 12 || got.Inbounds[1].Clients[0].Email != "shared@example.test" {
		t.Fatalf("shared client was not copied to second inbound: %#v", got.Inbounds[1].Clients)
	}
}

func TestPlanReplicationRejectsInvalidOrAmbiguousSourceRelationships(t *testing.T) {
	validInbound := []Inbound{{ID: 1, Tag: "in-443-tcp"}}
	validClient := []Client{{ID: 2, Email: "user@example.test"}}
	tests := []struct {
		name         string
		nodeID       int
		inbounds     []Inbound
		clients      []Client
		associations []ClientAssociation
	}{
		{name: "invalid target node", nodeID: 0, inbounds: validInbound},
		{name: "duplicate inbound id", nodeID: 7, inbounds: []Inbound{{ID: 1, Tag: "a"}, {ID: 1, Tag: "b"}}},
		{name: "duplicate source tag", nodeID: 7, inbounds: []Inbound{{ID: 1, Tag: "same"}, {ID: 2, Tag: "same"}}},
		{name: "duplicate global client email", nodeID: 7, inbounds: validInbound, clients: []Client{{ID: 2, Email: "same@example.test"}, {ID: 3, Email: "same@example.test"}}},
		{name: "association references missing inbound", nodeID: 7, inbounds: validInbound, clients: validClient, associations: []ClientAssociation{{InboundID: 99, ClientID: 2}}},
		{name: "association references missing client", nodeID: 7, inbounds: validInbound, clients: validClient, associations: []ClientAssociation{{InboundID: 1, ClientID: 99}}},
		{name: "duplicate association", nodeID: 7, inbounds: validInbound, clients: validClient, associations: []ClientAssociation{{InboundID: 1, ClientID: 2}, {InboundID: 1, ClientID: 2}}},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := PlanReplication(tc.nodeID, tc.inbounds, tc.clients, tc.associations); err == nil {
				t.Fatal("PlanReplication succeeded, want validation error")
			}
		})
	}
}

func TestPlanNodeDeletionIncludesAllAssociatedClientMastersEvenWhenShared(t *testing.T) {
	replicas := []ReplicaInbound{
		{ID: 42, TargetNodeID: 7, SourceInboundID: 2, Tag: "n7-in-8443-tcp", Clients: []ReplicaClient{{ClientID: 12, Email: "shared@example.test"}}},
		{ID: 41, TargetNodeID: 7, SourceInboundID: 1, Tag: "n7-in-443-tcp", Clients: []ReplicaClient{{ClientID: 12, Email: "shared@example.test"}, {ClientID: 11, Email: "other@example.test"}}},
	}

	got, err := PlanNodeDeletion(7, replicas)
	if err != nil {
		t.Fatalf("PlanNodeDeletion returned error: %v", err)
	}
	if got.NodeID != 7 || !reflect.DeepEqual(got.InboundIDs, []int{41, 42}) ||
		!reflect.DeepEqual(got.InboundTags, []string{"n7-in-443-tcp", "n7-in-8443-tcp"}) ||
		!reflect.DeepEqual(got.ClientIDs, []int{11, 12}) ||
		!reflect.DeepEqual(got.Clients, []ClientIdentity{{ID: 11, Email: "other@example.test"}, {ID: 12, Email: "shared@example.test"}}) {
		t.Fatalf("node deletion plan = %#v", got)
	}
}

func TestPlanNodeDeletionRefusesRecordsOutsideTargetNode(t *testing.T) {
	_, err := PlanNodeDeletion(7, []ReplicaInbound{{ID: 41, TargetNodeID: 8, SourceInboundID: 1, Tag: "n8-in-443-tcp"}})
	if err == nil {
		t.Fatal("PlanNodeDeletion accepted another node's inbound")
	}
}
