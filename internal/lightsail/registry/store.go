// Package registry persists Lightsail instance ownership and resumable panel cleanup.
package registry

import (
	"errors"
	"fmt"
	"regexp"
	"strings"

	"gorm.io/gorm"
	"gorm.io/gorm/clause"

	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
	lightsailconfig "github.com/mhsanaei/3x-ui/v3/internal/lightsail"
)

const (
	ManagedNodeProvisioning = "provisioning"
	ManagedNodeReady        = "ready"
	ManagedNodeCleanup      = "cleanup_pending"
	ManagedNodeDeleted      = "deleted"

	CleanupPrepared        = "prepared"
	CleanupInstanceDeleted = "instance_deleted"
	CleanupPanelCleaned    = "panel_cleaned"
	CleanupComplete        = "complete"
)

var idempotencyKeyPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$`)
var accountIDPattern = regexp.MustCompile(`^[0-9]{12}$`)
var regionPattern = regexp.MustCompile(`^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$`)
var instanceNamePattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9-]{0,61}[A-Za-z0-9]$`)

type Store struct{ db *gorm.DB }

type CleanupRequest struct {
	IdempotencyKey string
	AccountID      string
	ProfileName    string
	Region         string
	InstanceName   string
}

type InboundReplica struct {
	SourceInboundID  int
	NodeID           int
	ReplicaInboundID int
}

type ownershipProof struct {
	AccountID    string
	ProfileName  string
	Region       string
	InstanceName string
	Tags         map[string]string
}

func New(db *gorm.DB) *Store { return &Store{db: db} }

func (s *Store) registerNode(managed *model.LightsailManagedNode, proof ownershipProof) error {
	if s == nil || s.db == nil || managed == nil {
		return errors.New("Lightsail managed node storage is unavailable")
	}
	managed.AccountID = strings.TrimSpace(managed.AccountID)
	managed.ProfileName = strings.TrimSpace(managed.ProfileName)
	managed.Region = strings.TrimSpace(managed.Region)
	managed.InstanceName = strings.TrimSpace(managed.InstanceName)
	if !accountIDPattern.MatchString(managed.AccountID) || lightsailconfig.ValidateProfileName(managed.ProfileName) != nil || !regionPattern.MatchString(managed.Region) || !instanceNamePattern.MatchString(managed.InstanceName) || managed.NodeID <= 0 {
		return errors.New("Lightsail managed node identity is invalid")
	}
	if proof.AccountID != managed.AccountID || proof.ProfileName != managed.ProfileName || proof.Region != managed.Region || proof.InstanceName != managed.InstanceName ||
		proof.Tags[lightsailconfig.ManagedByTag] != lightsailconfig.ManagedByValue || proof.Tags[lightsailconfig.ProjectTag] != lightsailconfig.ProjectValue ||
		proof.Tags[lightsailconfig.AccountIDTag] != managed.AccountID || proof.Tags[lightsailconfig.ProfileNameTag] != managed.ProfileName {
		return errors.New("Lightsail instance ownership could not be verified")
	}
	var node model.Node
	if err := s.db.First(&node, managed.NodeID).Error; err != nil {
		return errors.New("Lightsail panel node mapping was not found")
	}
	if managed.State != "" && managed.State != ManagedNodeProvisioning {
		return errors.New("Lightsail managed node state is invalid")
	}
	managed.State = ManagedNodeProvisioning
	return s.db.Create(managed).Error
}

func (s *Store) registerInboundReplica(replica InboundReplica) error {
	if s == nil || s.db == nil || replica.SourceInboundID <= 0 || replica.NodeID <= 0 || replica.ReplicaInboundID <= 0 {
		return errors.New("Lightsail inbound replica identity is invalid")
	}
	var managed model.LightsailManagedNode
	if err := s.db.Where("node_id = ? AND state = ?", replica.NodeID, ManagedNodeReady).First(&managed).Error; err != nil {
		return errors.New("Lightsail inbound replica requires a ready managed node")
	}
	var source model.Inbound
	if err := s.db.Where("id = ? AND node_id IS NULL", replica.SourceInboundID).First(&source).Error; err != nil {
		return errors.New("Lightsail inbound replica source is not a master inbound")
	}
	var target model.Inbound
	if err := s.db.Where("id = ? AND node_id = ?", replica.ReplicaInboundID, replica.NodeID).First(&target).Error; err != nil {
		return errors.New("Lightsail inbound replica target is not attached to the managed node")
	}
	row := model.LightsailInboundReplica{
		SourceInboundID: replica.SourceInboundID, NodeID: replica.NodeID, ReplicaInboundID: replica.ReplicaInboundID,
	}
	return s.db.Create(&row).Error
}

func (s *Store) listInboundReplicas(nodeID int) ([]InboundReplica, error) {
	if s == nil || s.db == nil || nodeID <= 0 {
		return nil, errors.New("Lightsail inbound replica query is invalid")
	}
	var rows []model.LightsailInboundReplica
	if err := s.db.Where("node_id = ?", nodeID).Order("source_inbound_id asc").Find(&rows).Error; err != nil {
		return nil, errors.New("Lightsail inbound replicas could not be listed")
	}
	result := make([]InboundReplica, 0, len(rows))
	for _, row := range rows {
		result = append(result, InboundReplica{SourceInboundID: row.SourceInboundID, NodeID: row.NodeID, ReplicaInboundID: row.ReplicaInboundID})
	}
	return result, nil
}

// BeginCleanup persists a complete identity and relationship snapshot before a caller
// can perform any cloud or panel deletion. A retry with the same key returns that snapshot.
func (s *Store) BeginCleanup(request CleanupRequest) (model.LightsailCleanupIntent, error) {
	var intent model.LightsailCleanupIntent
	if s == nil || s.db == nil {
		return intent, errors.New("Lightsail cleanup storage is unavailable")
	}
	request.IdempotencyKey = strings.TrimSpace(request.IdempotencyKey)
	request.AccountID = strings.TrimSpace(request.AccountID)
	request.ProfileName = strings.TrimSpace(request.ProfileName)
	request.Region = strings.TrimSpace(request.Region)
	request.InstanceName = strings.TrimSpace(request.InstanceName)
	if !idempotencyKeyPattern.MatchString(request.IdempotencyKey) || !accountIDPattern.MatchString(request.AccountID) || lightsailconfig.ValidateProfileName(request.ProfileName) != nil || !regionPattern.MatchString(request.Region) || !instanceNamePattern.MatchString(request.InstanceName) {
		return intent, errors.New("Lightsail cleanup identity is invalid")
	}
	err := s.db.Transaction(func(tx *gorm.DB) error {
		var existing model.LightsailCleanupIntent
		if err := tx.Where("idempotency_key = ?", request.IdempotencyKey).First(&existing).Error; err == nil {
			if !sameCleanupTarget(existing, request) {
				return errors.New("Lightsail cleanup idempotency key conflicts with another instance")
			}
			intent = existing
			return nil
		} else if !errors.Is(err, gorm.ErrRecordNotFound) {
			return err
		}

		var managed model.LightsailManagedNode
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).Where(
			"account_id = ? AND profile_name = ? AND region = ? AND instance_name = ?",
			request.AccountID, request.ProfileName, request.Region, request.InstanceName,
		).First(&managed).Error; err != nil {
			return errors.New("Lightsail instance is not registered as project-managed")
		}
		if err := tx.Where("idempotency_key = ?", request.IdempotencyKey).First(&existing).Error; err == nil {
			if !sameCleanupTarget(existing, request) {
				return errors.New("Lightsail cleanup idempotency key conflicts with another instance")
			}
			intent = existing
			return nil
		} else if !errors.Is(err, gorm.ErrRecordNotFound) {
			return err
		}
		if managed.State != ManagedNodeReady {
			return errors.New("Lightsail managed instance is not ready for cleanup")
		}
		var node model.Node
		if err := tx.First(&node, managed.NodeID).Error; err != nil {
			return errors.New("Lightsail managed node has no panel node mapping")
		}
		var inboundIDs []int
		if err := tx.Model(&model.Inbound{}).Where("node_id = ?", managed.NodeID).Order("id asc").Pluck("id", &inboundIDs).Error; err != nil {
			return errors.New("Lightsail cleanup inbound snapshot failed")
		}
		if inboundIDs == nil {
			inboundIDs = []int{}
		}
		var clientIDs []int
		if err := tx.Table("client_inbounds").Distinct("client_inbounds.client_id").Joins("JOIN inbounds ON inbounds.id = client_inbounds.inbound_id").Where("inbounds.node_id = ?", managed.NodeID).Order("client_inbounds.client_id asc").Pluck("client_inbounds.client_id", &clientIDs).Error; err != nil {
			return errors.New("Lightsail cleanup client snapshot failed")
		}
		if clientIDs == nil {
			clientIDs = []int{}
		}
		intent = model.LightsailCleanupIntent{
			IdempotencyKey: request.IdempotencyKey, ManagedNodeID: managed.Id,
			AccountID: managed.AccountID, ProfileName: managed.ProfileName, Region: managed.Region, InstanceName: managed.InstanceName,
			NodeID: managed.NodeID, InboundIDs: inboundIDs, ClientIDs: clientIDs, Phase: CleanupPrepared,
		}
		if err := tx.Create(&intent).Error; err != nil {
			return err
		}
		if err := tx.Model(&managed).Update("state", ManagedNodeCleanup).Error; err != nil {
			return err
		}
		return nil
	})
	if err != nil {
		var existing model.LightsailCleanupIntent
		if lookupErr := s.db.Where("idempotency_key = ?", request.IdempotencyKey).First(&existing).Error; lookupErr == nil && sameCleanupTarget(existing, request) {
			return existing, nil
		}
		return model.LightsailCleanupIntent{}, err
	}
	return intent, nil
}

func (s *Store) advanceCleanup(intentID int, nextPhase string) error {
	if s == nil || s.db == nil || intentID <= 0 {
		return errors.New("Lightsail cleanup storage is unavailable")
	}
	nextRank, ok := cleanupPhaseRank(nextPhase)
	if !ok {
		return errors.New("Lightsail cleanup phase is invalid")
	}
	return s.db.Transaction(func(tx *gorm.DB) error {
		var intent model.LightsailCleanupIntent
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&intent, intentID).Error; err != nil {
			return errors.New("Lightsail cleanup intent was not found")
		}
		currentRank, _ := cleanupPhaseRank(intent.Phase)
		if nextRank == currentRank {
			return nil
		}
		if nextRank != currentRank+1 {
			return fmt.Errorf("Lightsail cleanup phase must advance one step from %s", intent.Phase)
		}
		if err := tx.Model(&intent).Update("phase", nextPhase).Error; err != nil {
			return errors.New("Lightsail cleanup phase could not be saved")
		}
		if nextPhase == CleanupComplete {
			if err := tx.Model(&model.LightsailManagedNode{}).Where("id = ?", intent.ManagedNodeID).Update("state", ManagedNodeDeleted).Error; err != nil {
				return errors.New("Lightsail managed instance state could not be saved")
			}
		}
		return nil
	})
}

func (s *Store) ListPendingCleanup(limit int) ([]model.LightsailCleanupIntent, error) {
	if s == nil || s.db == nil || limit < 1 || limit > 500 {
		return nil, errors.New("Lightsail cleanup query limit is invalid")
	}
	var intents []model.LightsailCleanupIntent
	if err := s.db.Where("phase <> ?", CleanupComplete).Order("id asc").Limit(limit).Find(&intents).Error; err != nil {
		return nil, errors.New("pending Lightsail cleanup intents could not be listed")
	}
	return intents, nil
}

func sameCleanupTarget(intent model.LightsailCleanupIntent, request CleanupRequest) bool {
	return intent.AccountID == request.AccountID && intent.ProfileName == request.ProfileName && intent.Region == request.Region && intent.InstanceName == request.InstanceName
}

func cleanupPhaseRank(phase string) (int, bool) {
	switch phase {
	case CleanupPrepared:
		return 0, true
	case CleanupInstanceDeleted:
		return 1, true
	case CleanupPanelCleaned:
		return 2, true
	case CleanupComplete:
		return 3, true
	default:
		return 0, false
	}
}
