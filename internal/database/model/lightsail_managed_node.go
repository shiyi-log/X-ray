package model

// LightsailManagedNode binds an instance created by this project to its panel node.
// It intentionally stores no AWS credentials or remote panel secrets.
type LightsailManagedNode struct {
	Id           int    `json:"id" gorm:"primaryKey;autoIncrement"`
	AccountID    string `json:"accountId" gorm:"column:account_id;not null;uniqueIndex:idx_lightsail_instance_owner,priority:1"`
	ProfileName  string `json:"profileName" gorm:"column:profile_name;not null"`
	Region       string `json:"region" gorm:"not null;uniqueIndex:idx_lightsail_instance_owner,priority:2"`
	InstanceName string `json:"instanceName" gorm:"column:instance_name;not null;uniqueIndex:idx_lightsail_instance_owner,priority:3"`
	NodeID       int    `json:"nodeId" gorm:"column:node_id;not null;uniqueIndex"`
	State        string `json:"state" gorm:"not null;default:provisioning;index"`
	CreatedAt    int64  `json:"createdAt" gorm:"autoCreateTime:milli"`
	UpdatedAt    int64  `json:"updatedAt" gorm:"autoUpdateTime:milli"`
}

func (LightsailManagedNode) TableName() string { return "lightsail_managed_nodes" }

// LightsailInboundReplica records one managed node's copy of a master inbound.
type LightsailInboundReplica struct {
	Id               int   `json:"id" gorm:"primaryKey;autoIncrement"`
	SourceInboundID  int   `json:"sourceInboundId" gorm:"column:source_inbound_id;not null;uniqueIndex:idx_lightsail_inbound_replica,priority:1"`
	NodeID           int   `json:"nodeId" gorm:"column:node_id;not null;uniqueIndex:idx_lightsail_inbound_replica,priority:2"`
	ReplicaInboundID int   `json:"replicaInboundId" gorm:"column:replica_inbound_id;not null;uniqueIndex"`
	CreatedAt        int64 `json:"createdAt" gorm:"autoCreateTime:milli"`
	UpdatedAt        int64 `json:"updatedAt" gorm:"autoUpdateTime:milli"`
}

func (LightsailInboundReplica) TableName() string { return "lightsail_inbound_replicas" }

// LightsailCleanupIntent freezes the panel IDs needed to resume a scale-down.
type LightsailCleanupIntent struct {
	Id             int    `json:"id" gorm:"primaryKey;autoIncrement"`
	IdempotencyKey string `json:"idempotencyKey" gorm:"column:idempotency_key;not null;uniqueIndex"`
	ManagedNodeID  int    `json:"managedNodeId" gorm:"column:managed_node_id;not null;index"`
	AccountID      string `json:"accountId" gorm:"column:account_id;not null"`
	ProfileName    string `json:"profileName" gorm:"column:profile_name;not null"`
	Region         string `json:"region" gorm:"not null"`
	InstanceName   string `json:"instanceName" gorm:"column:instance_name;not null"`
	NodeID         int    `json:"nodeId" gorm:"column:node_id;not null"`
	InboundIDs     []int  `json:"inboundIds" gorm:"column:inbound_ids;serializer:json;not null"`
	ClientIDs      []int  `json:"clientIds" gorm:"column:client_ids;serializer:json;not null"`
	Phase          string `json:"phase" gorm:"not null;index"`
	CreatedAt      int64  `json:"createdAt" gorm:"autoCreateTime:milli"`
	UpdatedAt      int64  `json:"updatedAt" gorm:"autoUpdateTime:milli"`
}

func (LightsailCleanupIntent) TableName() string { return "lightsail_cleanup_intents" }
