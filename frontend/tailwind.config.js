/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#0B0E14',
          900: '#0F131B',
          800: '#131820',
          700: '#1B2230',
          600: '#262E3D',
          500: '#3A4457',
        },
        parchment: {
          100: '#E7E9EE',
          300: '#AEB4C2',
          500: '#8B93A7',
        },
        brass: {
          400: '#DDBB4E',
          500: '#C9A227',
          600: '#9E7E1C',
        },
        risk: {
          low: '#3FA867',
          mid: '#D69A2D',
          high: '#D14F4F',
        },
      },
      fontFamily: {
        serif: ['"Source Serif 4"', 'Georgia', 'serif'],
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
};
