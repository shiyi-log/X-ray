// Package replicate builds deterministic plans for copying master inbound and
// client configuration to one managed node. It performs no database writes.
package replicate

import (
	"errors"
	"fmt"
	"sort"
	"strings"
)

// Inbound is the source panel configuration. Config is an opaque serialized
// inbound payload so protocol-specific fields remain intact.
type Inbound struct {
	ID     int
	Tag    string
	Config []byte
}

// Client is a globally unique master client record. Config must not be logged
// or formatted because it can contain client credentials.
type Client struct {
	ID     int
	Email  string
	Config []byte
}

// ClientAssociation carries fields stored on the client/inbound join.
type ClientAssociation struct {
	InboundID    int
	ClientID     int
	FlowOverride string
}

type ReplicaPlan struct {
	NodeID   int
	Inbounds []ReplicaInbound
}

type ReplicaInbound struct {
	ID              int
	SourceInboundID int
	TargetNodeID    int
	Tag             string
	Config          []byte
	Clients         []ReplicaClient
}

type ReplicaClient struct {
	ClientID     int
	Email        string
	Config       []byte
	FlowOverride string
}

type ClientIdentity struct {
	ID    int
	Email string
}

// PlanReplication copies all source inbounds and every client association to
// the target. Tags are prefixed by the panel's node ID to respect the global
// unique inbound tag constraint. Database IDs remain source references only;
// target IDs are left zero for the database to assign.
func PlanReplication(nodeID int, inbounds []Inbound, clients []Client, associations []ClientAssociation) (ReplicaPlan, error) {
	if nodeID <= 0 {
		return ReplicaPlan{}, errors.New("target node ID must be positive")
	}
	orderedInbounds := append([]Inbound(nil), inbounds...)
	sort.Slice(orderedInbounds, func(i, j int) bool { return orderedInbounds[i].ID < orderedInbounds[j].ID })
	orderedClients := append([]Client(nil), clients...)
	sort.Slice(orderedClients, func(i, j int) bool { return orderedClients[i].ID < orderedClients[j].ID })
	orderedAssociations := append([]ClientAssociation(nil), associations...)
	sort.Slice(orderedAssociations, func(i, j int) bool {
		if orderedAssociations[i].InboundID != orderedAssociations[j].InboundID {
			return orderedAssociations[i].InboundID < orderedAssociations[j].InboundID
		}
		return orderedAssociations[i].ClientID < orderedAssociations[j].ClientID
	})

	inboundByID := make(map[int]Inbound, len(orderedInbounds))
	for _, inbound := range orderedInbounds {
		if inbound.ID <= 0 || strings.TrimSpace(inbound.Tag) == "" {
			return ReplicaPlan{}, errors.New("source inbound identity is incomplete")
		}
		if _, exists := inboundByID[inbound.ID]; exists {
			return ReplicaPlan{}, errors.New("source inbound ID is duplicated")
		}
		inboundByID[inbound.ID] = inbound
	}
	clientByID := make(map[int]Client, len(orderedClients))
	clientByEmail := make(map[string]struct{}, len(orderedClients))
	for _, client := range orderedClients {
		email := strings.TrimSpace(client.Email)
		if client.ID <= 0 || email == "" {
			return ReplicaPlan{}, errors.New("source client identity is incomplete")
		}
		if _, exists := clientByID[client.ID]; exists {
			return ReplicaPlan{}, errors.New("source client ID is duplicated")
		}
		if _, exists := clientByEmail[email]; exists {
			return ReplicaPlan{}, errors.New("source client email is duplicated")
		}
		client.Email = email
		clientByID[client.ID] = client
		clientByEmail[email] = struct{}{}
	}

	replicas := make([]ReplicaInbound, 0, len(orderedInbounds))
	indexByInboundID := make(map[int]int, len(orderedInbounds))
	usedTags := make(map[string]struct{}, len(orderedInbounds))
	for _, inbound := range orderedInbounds {
		tag := fmt.Sprintf("n%d-%s", nodeID, inbound.Tag)
		if _, exists := usedTags[tag]; exists {
			return ReplicaPlan{}, errors.New("target inbound tag is duplicated")
		}
		usedTags[tag] = struct{}{}
		indexByInboundID[inbound.ID] = len(replicas)
		replicas = append(replicas, ReplicaInbound{
			SourceInboundID: inbound.ID, TargetNodeID: nodeID, Tag: tag, Config: cloneBytes(inbound.Config),
		})
	}
	seenAssociations := make(map[[2]int]struct{}, len(orderedAssociations))
	for _, association := range orderedAssociations {
		index, inboundExists := indexByInboundID[association.InboundID]
		client, clientExists := clientByID[association.ClientID]
		if !inboundExists || !clientExists {
			return ReplicaPlan{}, errors.New("client association references a missing source record")
		}
		key := [2]int{association.InboundID, association.ClientID}
		if _, exists := seenAssociations[key]; exists {
			return ReplicaPlan{}, errors.New("client association is duplicated")
		}
		seenAssociations[key] = struct{}{}
		replicas[index].Clients = append(replicas[index].Clients, ReplicaClient{
			ClientID: client.ID, Email: client.Email, Config: cloneBytes(client.Config), FlowOverride: association.FlowOverride,
		})
	}
	return ReplicaPlan{NodeID: nodeID, Inbounds: replicas}, nil
}

type DeletionPlan struct {
	NodeID      int
	InboundIDs  []int
	InboundTags []string
	ClientIDs   []int
	Clients     []ClientIdentity
}

// PlanNodeDeletion explicitly includes every client master record associated
// with the node, including identities also attached to other nodes/inbounds.
// This matches the user's destructive scale-down decision; callers must not
// substitute reference-counting semantics.
func PlanNodeDeletion(nodeID int, replicas []ReplicaInbound) (DeletionPlan, error) {
	if nodeID <= 0 {
		return DeletionPlan{}, errors.New("target node ID must be positive")
	}
	ordered := append([]ReplicaInbound(nil), replicas...)
	sort.Slice(ordered, func(i, j int) bool { return ordered[i].ID < ordered[j].ID })
	plan := DeletionPlan{NodeID: nodeID}
	seenInboundIDs := make(map[int]struct{}, len(ordered))
	seenTags := make(map[string]struct{}, len(ordered))
	clients := make(map[int]string)
	for _, inbound := range ordered {
		if inbound.TargetNodeID != nodeID {
			return DeletionPlan{}, errors.New("inbound is not owned by target node")
		}
		if inbound.ID <= 0 || inbound.SourceInboundID <= 0 || strings.TrimSpace(inbound.Tag) == "" {
			return DeletionPlan{}, errors.New("replica inbound identity is incomplete")
		}
		if _, exists := seenInboundIDs[inbound.ID]; exists {
			return DeletionPlan{}, errors.New("replica inbound ID is duplicated")
		}
		if _, exists := seenTags[inbound.Tag]; exists {
			return DeletionPlan{}, errors.New("replica inbound tag is duplicated")
		}
		seenInboundIDs[inbound.ID] = struct{}{}
		seenTags[inbound.Tag] = struct{}{}
		plan.InboundIDs = append(plan.InboundIDs, inbound.ID)
		plan.InboundTags = append(plan.InboundTags, inbound.Tag)
		for _, client := range inbound.Clients {
			if client.ClientID <= 0 || strings.TrimSpace(client.Email) == "" {
				return DeletionPlan{}, errors.New("replica client identity is incomplete")
			}
			if previous, exists := clients[client.ClientID]; exists && previous != client.Email {
				return DeletionPlan{}, errors.New("replica client identity is inconsistent")
			}
			clients[client.ClientID] = client.Email
		}
	}
	for id, email := range clients {
		plan.ClientIDs = append(plan.ClientIDs, id)
		plan.Clients = append(plan.Clients, ClientIdentity{ID: id, Email: email})
	}
	sort.Ints(plan.ClientIDs)
	sort.Slice(plan.Clients, func(i, j int) bool { return plan.Clients[i].ID < plan.Clients[j].ID })
	return plan, nil
}

func cloneBytes(value []byte) []byte {
	return append([]byte(nil), value...)
}
