import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {viteSingleFile} from 'vite-plugin-singlefile';

// Preview-only: one self-contained HTML file that opens from disk.
export default defineConfig({plugins: [react(), viteSingleFile()], build: {outDir: 'dist-single', emptyOutDir: true}});
