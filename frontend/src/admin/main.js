// 관리자 페이지 진입점 — 사용자 화면(index.html)과 다른 페이지. 스타일은 같은 파일을 쓴다
import { createApp } from 'vue'
import AdminApp from './AdminApp.vue'
import '../style.css'

createApp(AdminApp).mount('#admin')
