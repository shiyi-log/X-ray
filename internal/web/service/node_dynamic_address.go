package service

import (
	"context"
	"errors"
	"fmt"
	"net/netip"
	"strings"

	"github.com/mhsanaei/3x-ui/v3/internal/database"
	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
	"github.com/mhsanaei/3x-ui/v3/internal/web/runtime"
	"gorm.io/gorm"
)

// CheckHealthyAfterRestart verifies both the remote panel API and its Xray core
// after a managed node has been restarted.
func (s *NodeService) CheckHealthyAfterRestart(ctx context.Context, node *model.Node) error {
	if node == nil || node.Id <= 0 {
		return errors.New("node is unavailable for health check")
	}
	patch, err := s.Probe(ctx, node)
	if err != nil {
		return errors.New("node panel API health check failed")
	}
	if !strings.EqualFold(strings.TrimSpace(patch.XrayState), "running") {
		return errors.New("node Xray core is not running")
	}
	return nil
}

// UpdateDynamicIPv4 updates only the node API address after a managed Lightsail
// instance returns from Stop/Start. It deliberately leaves all node and inbound
// sharing/host settings untouched.
func (s *NodeService) UpdateDynamicIPv4(nodeID int, address netip.Addr) error {
	if nodeID <= 0 {
		return errors.New("node ID must be positive")
	}
	if !address.IsValid() || !address.Is4() || address.IsUnspecified() {
		return errors.New("Lightsail node requires a valid dynamic IPv4 address")
	}
	db := database.GetDB()
	if db == nil {
		return errors.New("node database is unavailable")
	}
	result := db.Model(&model.Node{}).Where("id = ?", nodeID).UpdateColumn("address", address.String())
	if result.Error != nil {
		return fmt.Errorf("update Lightsail node API address: %w", result.Error)
	}
	if result.RowsAffected == 0 {
		var exists int64
		if err := db.Model(&model.Node{}).Where("id = ?", nodeID).Count(&exists).Error; err != nil {
			return fmt.Errorf("verify Lightsail node exists: %w", err)
		}
		if exists == 0 {
			return gorm.ErrRecordNotFound
		}
	}
	if manager := runtime.GetManager(); manager != nil {
		manager.InvalidateNode(nodeID)
	}
	return nil
}
