import { describe, expect, it } from 'vitest';

import { AllSetting } from '@/models/setting';
import { AllSettingSchema } from '@/schemas/setting';

describe('Lightsail settings', () => {
  it('defaults automation to the backend Lightsail contract', () => {
    const setting = new AllSetting();

    expect(setting.lightsailScaleEnabled).toBe(false);
    expect(setting.lightsailDailyRestartEnabled).toBe(false);
    expect(setting.lightsailRestartTime).toBe('04:00');
    expect(setting.lightsailTimeZone).toBe('Asia/Shanghai');
    expect(setting.lightsailRegionTargets).toBe('[]');
  });

  it('accepts profile, region targets, and a valid restart time', () => {
    const result = AllSettingSchema.safeParse({
      lightsailProfileName: 'production-panel',
      lightsailRegionTargets:
        '[{"region":"ap-southeast-1","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":2}]',
      lightsailScaleEnabled: true,
      lightsailDailyRestartEnabled: true,
      lightsailRestartTime: '04:00',
      lightsailTimeZone: 'Asia/Shanghai',
    });

    expect(result.success).toBe(true);
  });

  it('rejects invalid restart time strings', () => {
    expect(AllSettingSchema.safeParse({ lightsailRestartTime: '24:60' }).success).toBe(false);
  });

  it('rejects invalid Lightsail time zones', () => {
    expect(AllSettingSchema.safeParse({ lightsailTimeZone: 'Not/AZone' }).success).toBe(false);
  });

  it('requires a named profile when a region target is configured', () => {
    const result = AllSettingSchema.safeParse({
      lightsailRegionTargets:
        '[{"region":"ap-southeast-1","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":1}]',
    });

    expect(result.success).toBe(false);
  });

  it('rejects malformed or destructive region targets before saving', () => {
    expect(
      AllSettingSchema.safeParse({
        lightsailRegionTargets:
          '[{\"region\":\"ap-southeast-1\",\"bundleId\":\"small_3_0\",\"blueprintId\":\"ubuntu_24_04\",\"targetCount\":-1}]',
      }).success,
    ).toBe(false);
  });
});
