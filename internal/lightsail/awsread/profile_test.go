package awsread

import "testing"

func TestRejectCredentialEnvironmentOverridesForNamedProfiles(t *testing.T) {
	for _, key := range []string{
		"AWS_ACCESS_KEY_ID",
		"AWS_SECRET_ACCESS_KEY",
		"AWS_SESSION_TOKEN",
		"AWS_WEB_IDENTITY_TOKEN_FILE",
		"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
		"AWS_CONTAINER_CREDENTIALS_FULL_URI",
	} {
		t.Run(key, func(t *testing.T) {
			err := validateCredentialEnvironment(func(name string) (string, bool) {
				return "sensitive-value", name == key
			})
			if err == nil {
				t.Fatalf("accepted credential override variable %s", key)
			}
			if got := err.Error(); got != "credential override environment is not allowed with an AWS named profile" {
				t.Fatalf("error = %q, must stay generic", got)
			}
		})
	}
}

func TestAllowsUnrelatedAWSEnvironmentVariables(t *testing.T) {
	if err := validateCredentialEnvironment(func(name string) (string, bool) {
		return "us-east-1", name == "AWS_DEFAULT_REGION"
	}); err != nil {
		t.Fatalf("unrelated AWS region environment blocked profile: %v", err)
	}
}
