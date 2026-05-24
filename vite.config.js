import { resolve } from 'path';

export default {
  root: 'public',
  server: {
    port: 3000,
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve('public', 'index.html'),
        dbtPackages: resolve('public', 'dbt-packages', 'index.html'),
        dbtFusion: resolve('public', 'dbt-fusion', 'index.html'),
        security: resolve('public', 'security', 'index.html'),
        bigquery: resolve('public', 'bigquery', 'index.html'),
        lakehouse: resolve('public', 'lakehouse', 'index.html'),
      },
    },
  },
}
