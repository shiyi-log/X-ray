import { describe, expect, it } from 'vitest';

import {
  parseLightsailRegionTargets,
  serializeLightsailRegionTargets,
} from '@/lib/lightsail/targets';

describe('Lightsail region targets', () => {
  it('round trips regional bundle choices and permits a zero target', () => {
    const input = [
      {
        region: 'ap-southeast-1',
        availabilityZone: 'ap-southeast-1a',
        bundleId: 'small_3_0',
        blueprintId: 'ubuntu_24_04',
        targetCount: 0,
      },
    ];

    const serialized = serializeLightsailRegionTargets(input);

    expect(serialized).toBe(
      '[{"region":"ap-southeast-1","availabilityZone":"ap-southeast-1a","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":0}]',
    );
    expect(parseLightsailRegionTargets(serialized)).toEqual(input);
  });

  it.each([
    '[{"region":"ap-southeast-1","availabilityZone":"ap-southeast-1a","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":-1}]',
    '[{"region":"ap-southeast-1","availabilityZone":"ap-southeast-1a","bundleId":"","blueprintId":"ubuntu_24_04","targetCount":1}]',
    '[{"region":"ap-southeast-1","availabilityZone":"ap-southeast-1a","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":1},{"region":"ap-southeast-1","availabilityZone":"ap-southeast-1a","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":2}]',
    '{not-json}',
  ])('rejects unsafe or malformed stored values: %s', (value) => {
    expect(() => parseLightsailRegionTargets(value)).toThrow();
  });

  it('accepts Lightsail regions containing a hyphenated geographic name', () => {
    expect(
      parseLightsailRegionTargets(
        '[{"region":"us-gov-west-1","availabilityZone":"us-gov-west-1a","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":1}]',
      )[0]?.region,
    ).toBe('us-gov-west-1');
  });
});
