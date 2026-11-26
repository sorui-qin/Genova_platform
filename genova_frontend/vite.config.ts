import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import autoprefixer from 'autoprefixer'
import { visualizer } from 'rollup-plugin-visualizer'
import tailwind from 'tailwindcss'
import AutoImport from 'unplugin-auto-import/vite'
import Component from 'unplugin-vue-components/vite'
import { defineConfig, loadEnv } from 'vite'
import Pages from 'vite-plugin-pages'
import vueDevTools from 'vite-plugin-vue-devtools'
import Layouts from 'vite-plugin-vue-layouts'

const targetUrl = 'http://127.0.0.1:18000'
const defaultBasePath = '/genova/'

function normalizeBasePath(basePath?: string): string {
  const rawBasePath = (basePath || defaultBasePath).trim()
  if (!rawBasePath || rawBasePath === '/') {
    return '/'
  }

  const withoutEdgeSlashes = rawBasePath.replace(/^\/+|\/+$/g, '')
  if (!withoutEdgeSlashes) {
    return '/'
  }

  return `/${withoutEdgeSlashes}/`
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const basePath = normalizeBasePath(env.VITE_APP_BASE_PATH)
  const prefixedApiPath = `${basePath}api`
  const prefixedWsPath = `${basePath}ws`

  return {
    base: basePath,
    build: {
      rollupOptions: {
        output: {
          onlyExplicitManualChunks: true,
          manualChunks(id) {
            if (id.includes('/node_modules/tslib/')) return 'tslib'
            if (id.includes('/node_modules/molstar/')) return 'molstar'
          },
        },
      },
    },
    optimizeDeps: {
      entries: ['index.html', 'src/pages/**/*.vue'],
      include: [
        'echarts',
        'zrender',
      ],
    },
    plugins: [
      vue(),
      vueJsx(),
      env.VITE_DEVTOOLS === 'true' && vueDevTools(),
      visualizer({ gzipSize: true, brotliSize: true }),
      Pages({
        routeStyle: 'nuxt',
        exclude: [
          '**/components/**',
          '**/layouts/**',
          '**/data/**',
          '**/types/**',
        ],
      }),
      Layouts({
        defaultLayout: 'default',
      }),
      AutoImport({
        include: [
          /\.[tj]sx?$/, // .ts, .tsx, .js, .jsx
          /\.vue$/,
          /\.md$/, // .md
        ],
        imports: [
          'vue',
          'vue-router',
        ], // 自动加载 vue,vue-router api
        dirs: [
          'src/composables/**/*.ts',
          'src/enum/**/*.ts',
          'src/store/**/*.ts',
        ], // 自动加载配置里的文件
        defaultExportByFilename: true, // 包含文件夹名称，避免命名冲突
        dts: 'src/types/auto-import.d.ts', // 类型提示文件
      }),
      Component({
        dirs: [
          'src/components',
        ],
        collapseSamePrefixes: true,
        directoryAsNamespace: true, // 包含文件夹名称，避免命名冲突
        dts: 'src/types/auto-import-components.d.ts', // 类型提示文件
      }),
    ],
    css: {
      postcss: {
        plugins: [tailwind(), autoprefixer()],
      },
    },
    server: {
      host: '0.0.0.0',
      port: 18001,
      strictPort: true,
      proxy: {
        '/api': {
          target: targetUrl,
          changeOrigin: true,
          configure(proxy) {
            proxy.on('proxyReq', (proxyReq, req) => {
              proxyReq.setHeader('X-Forwarded-For', req.socket.remoteAddress || '')
            })
          },
        },
        [prefixedApiPath]: {
          target: targetUrl,
          changeOrigin: true,
          configure(proxy) {
            proxy.on('proxyReq', (proxyReq, req) => {
              proxyReq.setHeader('X-Forwarded-For', req.socket.remoteAddress || '')
            })
          },
          rewrite: path => path.slice(basePath.length - 1),
        },
        '/ws': {
          target: targetUrl,
          changeOrigin: true,
          ws: true,
        },
        [prefixedWsPath]: {
          target: targetUrl,
          changeOrigin: true,
          ws: true,
          rewrite: path => path.slice(basePath.length - 1),
        },
      }
    },
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
        '@/components': fileURLToPath(new URL('./src/components', import.meta.url)),
      },
    },
  }
})
