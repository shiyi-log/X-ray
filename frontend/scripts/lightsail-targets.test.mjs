import assert from 'node:assert/strict';
import test from 'node:test';

import { parseLightsailRegionTargets, serializeLightsailRegionTargets } from '../src/lib/lightsail/targets.ts';

test('Lightsail targets preserve configured plans and allow target zero', () => {
  const targets = [
    {
      region: 'ap-southeast-1',
      availabilityZone: 'ap-southeast-1a',
      bundleId: 'small_3_0',
      blueprintId: 'ubuntu_24_04',
      targetCount: 0,
    },
  ];
  const saved = serializeLightsailRegionTargets(targets);
  assert.equal(
    saved,
    '[{"region":"ap-southeast-1","availabilityZone":"ap-southeast-1a","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":0}]',
  );
  assert.deepEqual(parseLightsailRegionTargets(saved), targets);
});

test('Lightsail targets reject malformed, duplicate, incomplete and negative rows', () => {
  for (const value of [
    '{not-json}',
    '[{"region":"ap-southeast-1","bundleId":"","blueprintId":"ubuntu_24_04","targetCount":1}]',
    '[{"region":"ap-southeast-1","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":-1}]',
    '[{"region":"ap-southeast-1","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":1},{"region":"ap-southeast-1","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":2}]',
  ]) {
    assert.throws(() => parseLightsailRegionTargets(value));
  }
});
