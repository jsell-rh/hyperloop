export default defineNuxtConfig({
  compatibilityDate: '2025-01-01',
  future: { compatibilityVersion: 4 },
  devtools: { enabled: true },
  modules: ['@nuxtjs/tailwindcss'],
  devServer: {
    port: 3000,
  },
  nitro: {
    devProxy: {
      '/api': {
        target: 'http://localhost:8787',
        changeOrigin: true,
      },
    },
  },
})
