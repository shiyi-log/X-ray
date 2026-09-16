# OpenAPI 生成物

`schema.yaml` 由 `manage.py spectacular --validate` 生成，前端类型由
`frontend/scripts/generate-api.mjs` 从该文件生成。两个文件都应提交，禁止手工修改
生成的 TypeScript。
