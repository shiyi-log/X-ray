import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

import openapiTS, { astToString, COMMENT_HEADER } from 'openapi-typescript';

const schemaUrl = new URL('../../backend/openapi/schema.yaml', import.meta.url);
const outputUrl = new URL(
  '../apps/web-antd/src/api/generated/schema.ts',
  import.meta.url,
);

const nodes = await openapiTS(schemaUrl, {
  alphabetize: true,
  immutable: true,
});
const outputPath = fileURLToPath(outputUrl);
await mkdir(new URL('../apps/web-antd/src/api/generated/', import.meta.url), {
  recursive: true,
});
await writeFile(
  outputPath,
  `${COMMENT_HEADER}\n// Source: backend/openapi/schema.yaml. Do not edit manually.\n${astToString(nodes)}`,
  'utf8',
);
