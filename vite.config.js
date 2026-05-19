export default {
  root: 'public',
  server: {
    port: 3000,
    proxy: {
      '/digest': 'http://localhost:8080',
      '/health':  'http://localhost:8080',
      '/trigger': 'http://localhost:8080',
    },
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true,
  },
}
