// Vite 설정 — 개발 서버는 5173 고정 (백엔드 CORS 허용 출처와 맞춘다. 포트가 바뀌면 CORS에 막힘)
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  test: { environment: 'node' },
})
