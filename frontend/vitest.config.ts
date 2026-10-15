import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Tests run in Node against `react-dom/server`: the renderers only produce
// markup, so no DOM environment (jsdom, happy-dom) is needed and neither is a
// dependency. `react` is kept as a plugin so `.tsx` test files get the
// automatic JSX runtime, exactly like the app build.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
