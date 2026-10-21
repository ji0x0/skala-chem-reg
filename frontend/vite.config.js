// Vite 설정 — 개발 서버는 5173 고정 (백엔드 CORS 허용 출처와 맞춘다. 포트가 바뀌면 CORS에 막힘)
import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  // 페이지 2개: 사용자 화면(index.html)과 관리자 페이지(admin.html — 사용자 화면 메뉴에는 없다)
  build: { rollupOptions: { input: { main: resolve(__dirname, 'index.html'), admin: resolve(__dirname, 'admin.html') } } },
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  test: { environment: 'node' },
})
