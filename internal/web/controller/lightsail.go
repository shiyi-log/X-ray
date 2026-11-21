package controller

import (
	"context"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/mhsanaei/3x-ui/v3/internal/lightsail"
	"github.com/mhsanaei/3x-ui/v3/internal/lightsail/awsread"
)

type lightsailReader interface {
	Identity(context.Context) (awsread.Identity, error)
	Regions(context.Context) ([]awsread.Region, error)
	AvailabilityZones(context.Context, string) ([]string, error)
	Bundles(context.Context, string) ([]awsread.Bundle, error)
	Blueprints(context.Context, string) ([]awsread.Blueprint, error)
}

type lightsailProfileForm struct {
	ProfileName string  `json:"profileName"`
	Region      *string `json:"region"`
}

func (a *SettingController) lightsailReader(c *gin.Context, profile string) (lightsailReader, bool) {
	profile = strings.TrimSpace(profile)
	if err := lightsail.ValidateProfileName(profile); err != nil {
		pureJsonMsg(c, http.StatusOK, false, "A valid saved AWS named profile is required")
		return nil, false
	}
	factory := a.lightsailReaderFactory
	if factory == nil {
		factory = func(ctx context.Context, profile string) (lightsailReader, error) {
			return awsread.NewFromProfile(ctx, profile)
		}
	}
	reader, err := factory(c.Request.Context(), profile)
	if err != nil || reader == nil {
		pureJsonMsg(c, http.StatusOK, false, "AWS named profile could not be loaded")
		return nil, false
	}
	return reader, true
}

func (a *SettingController) verifyLightsailProfile(c *gin.Context) {
	var form lightsailProfileForm
	if err := c.ShouldBindJSON(&form); err != nil {
		pureJsonMsg(c, http.StatusOK, false, "A valid AWS named profile is required")
		return
	}
	reader, ok := a.lightsailReader(c, form.ProfileName)
	if !ok {
		return
	}
	identity, err := reader.Identity(c.Request.Context())
	if err != nil {
		pureJsonMsg(c, http.StatusOK, false, "AWS profile verification failed")
		return
	}
	jsonObj(c, identity, nil)
}

func (a *SettingController) listLightsailRegions(c *gin.Context) {
	var form lightsailProfileForm
	if err := c.ShouldBindJSON(&form); err != nil {
		pureJsonMsg(c, http.StatusOK, false, "A valid AWS named profile is required")
		return
	}
	reader, ok := a.lightsailReader(c, form.ProfileName)
	if !ok {
		return
	}
	regions, err := reader.Regions(c.Request.Context())
	if err != nil {
		pureJsonMsg(c, http.StatusOK, false, "Lightsail regions could not be read")
		return
	}
	jsonObj(c, regions, nil)
}

func (a *SettingController) listLightsailZones(c *gin.Context) {
	var form lightsailProfileForm
	if err := c.ShouldBindJSON(&form); err != nil {
		pureJsonMsg(c, http.StatusOK, false, "A valid Lightsail region is required")
		return
	}
	region := ""
	if form.Region != nil {
		region = strings.TrimSpace(*form.Region)
	}
	if err := lightsail.ValidateRegion(region); err != nil {
		pureJsonMsg(c, http.StatusOK, false, "A valid Lightsail region is required")
		return
	}
	reader, ok := a.lightsailReader(c, form.ProfileName)
	if !ok {
		return
	}
	zones, err := reader.AvailabilityZones(c.Request.Context(), region)
	if err != nil {
		pureJsonMsg(c, http.StatusOK, false, "Lightsail availability zones could not be read")
		return
	}
	jsonObj(c, zones, nil)
}

func (a *SettingController) getLightsailCatalog(c *gin.Context) {
	var form lightsailProfileForm
	if err := c.ShouldBindJSON(&form); err != nil {
		pureJsonMsg(c, http.StatusOK, false, "A valid Lightsail region is required")
		return
	}
	region := ""
	if form.Region != nil {
		region = strings.TrimSpace(*form.Region)
	}
	if err := lightsail.ValidateRegion(region); err != nil {
		pureJsonMsg(c, http.StatusOK, false, "A valid Lightsail region is required")
		return
	}
	reader, ok := a.lightsailReader(c, form.ProfileName)
	if !ok {
		return
	}
	bundles, err := reader.Bundles(c.Request.Context(), region)
	if err != nil {
		pureJsonMsg(c, http.StatusOK, false, "Lightsail bundles could not be read")
		return
	}
	blueprints, err := reader.Blueprints(c.Request.Context(), region)
	if err != nil {
		pureJsonMsg(c, http.StatusOK, false, "Lightsail blueprints could not be read")
		return
	}
	jsonObj(c, gin.H{"bundles": bundles, "blueprints": blueprints}, nil)
}
