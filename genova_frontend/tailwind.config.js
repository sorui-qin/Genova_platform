const animate = require('tailwindcss-animate')

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ['class'],
  safelist: ['dark'],
  prefix: '',

  content: [
    './pages/**/*.{ts,tsx,vue}',
    './components/**/*.{ts,tsx,vue}',
    './app/**/*.{ts,tsx,vue}',
    './src/**/*.{ts,tsx,vue}',
  ],

  theme: {
  	container: {
  		center: true,
  		padding: '2rem',
  		screens: {
  			'2xl': '1400px'
  		}
  	},
  	extend: {
  		colors: {
            slate: { 50: 'rgb(var(--surface-secondary-rgb) / <alpha-value>)', 100: 'rgb(var(--surface-secondary-rgb) / <alpha-value>)', 200: 'rgb(var(--border-default-rgb) / <alpha-value>)', 300: 'rgb(var(--border-emphasis-rgb) / <alpha-value>)', 400: 'rgb(var(--text-secondary-rgb) / <alpha-value>)', 500: 'rgb(var(--text-secondary-rgb) / <alpha-value>)', 600: 'rgb(var(--text-secondary-rgb) / <alpha-value>)', 700: 'rgb(var(--text-primary-rgb) / <alpha-value>)', 800: 'rgb(var(--text-primary-rgb) / <alpha-value>)', 900: 'rgb(var(--text-primary-rgb) / <alpha-value>)', 950: 'rgb(var(--text-primary-rgb) / <alpha-value>)' },
            gray: { 50: 'rgb(var(--surface-secondary-rgb) / <alpha-value>)', 100: 'rgb(var(--surface-secondary-rgb) / <alpha-value>)', 200: 'rgb(var(--border-default-rgb) / <alpha-value>)', 300: 'rgb(var(--border-emphasis-rgb) / <alpha-value>)', 400: 'rgb(var(--text-secondary-rgb) / <alpha-value>)', 500: 'rgb(var(--text-secondary-rgb) / <alpha-value>)', 600: 'rgb(var(--text-secondary-rgb) / <alpha-value>)', 700: 'rgb(var(--text-primary-rgb) / <alpha-value>)', 800: 'rgb(var(--text-primary-rgb) / <alpha-value>)', 900: 'rgb(var(--text-primary-rgb) / <alpha-value>)', 950: 'rgb(var(--text-primary-rgb) / <alpha-value>)' },
            blue: { 50: 'rgb(var(--selection-bg-rgb) / <alpha-value>)', 100: 'rgb(var(--selection-bg-rgb) / <alpha-value>)', 200: 'rgb(var(--border-emphasis-rgb) / <alpha-value>)', 300: 'rgb(var(--border-emphasis-rgb) / <alpha-value>)', 400: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 500: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 600: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 700: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 800: 'rgb(var(--action-hover-rgb) / <alpha-value>)', 900: 'rgb(var(--text-primary-rgb) / <alpha-value>)' },
            violet: { 50: 'rgb(var(--selection-bg-rgb) / <alpha-value>)', 100: 'rgb(var(--selection-bg-rgb) / <alpha-value>)', 200: 'rgb(var(--border-emphasis-rgb) / <alpha-value>)', 300: 'rgb(var(--border-emphasis-rgb) / <alpha-value>)', 400: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 500: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 600: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 700: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 800: 'rgb(var(--action-hover-rgb) / <alpha-value>)', 900: 'rgb(var(--text-primary-rgb) / <alpha-value>)' },
            purple: { 50: 'rgb(var(--selection-bg-rgb) / <alpha-value>)', 100: 'rgb(var(--selection-bg-rgb) / <alpha-value>)', 200: 'rgb(var(--border-emphasis-rgb) / <alpha-value>)', 300: 'rgb(var(--border-emphasis-rgb) / <alpha-value>)', 400: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 500: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 600: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 700: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 800: 'rgb(var(--action-hover-rgb) / <alpha-value>)', 900: 'rgb(var(--text-primary-rgb) / <alpha-value>)' },
            indigo: { 50: 'rgb(var(--selection-bg-rgb) / <alpha-value>)', 100: 'rgb(var(--selection-bg-rgb) / <alpha-value>)', 200: 'rgb(var(--border-emphasis-rgb) / <alpha-value>)', 300: 'rgb(var(--border-emphasis-rgb) / <alpha-value>)', 400: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 500: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 600: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 700: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 800: 'rgb(var(--action-hover-rgb) / <alpha-value>)', 900: 'rgb(var(--text-primary-rgb) / <alpha-value>)' },
            sky: { 50: 'rgb(var(--selection-bg-rgb) / <alpha-value>)', 100: 'rgb(var(--selection-bg-rgb) / <alpha-value>)', 200: 'rgb(var(--border-emphasis-rgb) / <alpha-value>)', 300: 'rgb(var(--border-emphasis-rgb) / <alpha-value>)', 400: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 500: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 600: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 700: 'rgb(var(--action-primary-rgb) / <alpha-value>)', 800: 'rgb(var(--action-hover-rgb) / <alpha-value>)', 900: 'rgb(var(--text-primary-rgb) / <alpha-value>)' },
            emerald: { 50: 'rgb(var(--status-success-bg-rgb) / <alpha-value>)', 100: 'rgb(var(--status-success-bg-rgb) / <alpha-value>)', 500: 'rgb(var(--status-success-rgb) / <alpha-value>)', 600: 'rgb(var(--status-success-rgb) / <alpha-value>)', 700: 'rgb(var(--status-success-rgb) / <alpha-value>)', 800: 'rgb(var(--status-success-rgb) / <alpha-value>)', 900: 'rgb(var(--status-success-rgb) / <alpha-value>)' },
            green: { 50: 'rgb(var(--status-success-bg-rgb) / <alpha-value>)', 100: 'rgb(var(--status-success-bg-rgb) / <alpha-value>)', 500: 'rgb(var(--status-success-rgb) / <alpha-value>)', 600: 'rgb(var(--status-success-rgb) / <alpha-value>)', 700: 'rgb(var(--status-success-rgb) / <alpha-value>)', 800: 'rgb(var(--status-success-rgb) / <alpha-value>)', 900: 'rgb(var(--status-success-rgb) / <alpha-value>)' },
            teal: { 50: 'rgb(var(--status-success-bg-rgb) / <alpha-value>)', 100: 'rgb(var(--status-success-bg-rgb) / <alpha-value>)', 500: 'rgb(var(--status-success-rgb) / <alpha-value>)', 600: 'rgb(var(--status-success-rgb) / <alpha-value>)', 700: 'rgb(var(--status-success-rgb) / <alpha-value>)', 800: 'rgb(var(--status-success-rgb) / <alpha-value>)', 900: 'rgb(var(--status-success-rgb) / <alpha-value>)' },
            amber: { 50: 'rgb(var(--status-pending-bg-rgb) / <alpha-value>)', 100: 'rgb(var(--status-pending-bg-rgb) / <alpha-value>)', 500: 'rgb(var(--status-pending-rgb) / <alpha-value>)', 600: 'rgb(var(--status-pending-rgb) / <alpha-value>)', 700: 'rgb(var(--status-pending-rgb) / <alpha-value>)', 800: 'rgb(var(--status-pending-rgb) / <alpha-value>)', 900: 'rgb(var(--status-pending-rgb) / <alpha-value>)' },
            orange: { 50: 'rgb(var(--status-pending-bg-rgb) / <alpha-value>)', 100: 'rgb(var(--status-pending-bg-rgb) / <alpha-value>)', 500: 'rgb(var(--status-pending-rgb) / <alpha-value>)', 600: 'rgb(var(--status-pending-rgb) / <alpha-value>)', 700: 'rgb(var(--status-pending-rgb) / <alpha-value>)', 800: 'rgb(var(--status-pending-rgb) / <alpha-value>)', 900: 'rgb(var(--status-pending-rgb) / <alpha-value>)' },
            red: { 50: 'rgb(var(--status-failed-bg-rgb) / <alpha-value>)', 100: 'rgb(var(--status-failed-bg-rgb) / <alpha-value>)', 500: 'rgb(var(--status-failed-rgb) / <alpha-value>)', 600: 'rgb(var(--status-failed-rgb) / <alpha-value>)', 700: 'rgb(var(--status-failed-rgb) / <alpha-value>)', 800: 'rgb(var(--status-failed-rgb) / <alpha-value>)', 900: 'rgb(var(--status-failed-rgb) / <alpha-value>)' },
            rose: { 50: 'rgb(var(--status-failed-bg-rgb) / <alpha-value>)', 100: 'rgb(var(--status-failed-bg-rgb) / <alpha-value>)', 500: 'rgb(var(--status-failed-rgb) / <alpha-value>)', 600: 'rgb(var(--status-failed-rgb) / <alpha-value>)', 700: 'rgb(var(--status-failed-rgb) / <alpha-value>)', 800: 'rgb(var(--status-failed-rgb) / <alpha-value>)', 900: 'rgb(var(--status-failed-rgb) / <alpha-value>)' },
            border: 'hsl(var(--border))',
  			input: 'hsl(var(--input))',
  			ring: 'hsl(var(--ring))',
  			background: 'hsl(var(--background))',
  			foreground: 'hsl(var(--foreground))',
  			primary: {
  				DEFAULT: 'hsl(var(--primary))',
  				foreground: 'hsl(var(--primary-foreground))'
  			},
  			secondary: {
  				DEFAULT: 'hsl(var(--secondary))',
  				foreground: 'hsl(var(--secondary-foreground))'
  			},
  			destructive: {
  				DEFAULT: 'hsl(var(--destructive))',
  				foreground: 'hsl(var(--destructive-foreground))'
  			},
  			muted: {
  				DEFAULT: 'hsl(var(--muted))',
  				foreground: 'hsl(var(--muted-foreground))'
  			},
  			accent: {
  				DEFAULT: 'hsl(var(--accent))',
  				foreground: 'hsl(var(--accent-foreground))'
  			},
  			popover: {
  				DEFAULT: 'hsl(var(--popover))',
  				foreground: 'hsl(var(--popover-foreground))'
  			},
  			card: {
  				DEFAULT: 'hsl(var(--card))',
  				foreground: 'hsl(var(--card-foreground))'
  			},
  			sidebar: {
  				DEFAULT: 'hsl(var(--sidebar-background))',
  				foreground: 'hsl(var(--sidebar-foreground))',
  				primary: 'hsl(var(--sidebar-primary))',
  				'primary-foreground': 'hsl(var(--sidebar-primary-foreground))',
  				accent: 'hsl(var(--sidebar-accent))',
  				'accent-foreground': 'hsl(var(--sidebar-accent-foreground))',
  				border: 'hsl(var(--sidebar-border))',
  				ring: 'hsl(var(--sidebar-ring))'
  			},
  			chart: {
  				'1': 'hsl(var(--chart-1))',
  				'2': 'hsl(var(--chart-2))',
  				'3': 'hsl(var(--chart-3))',
  				'4': 'hsl(var(--chart-4))',
  				'5': 'hsl(var(--chart-5))'
  			}
  		},
  		borderRadius: {
            xl: '12px',
            lg: '8px',
            md: '8px',
            sm: '4px'
  		},
  		keyframes: {
  			'accordion-down': {
  				from: {
  					height: 0
  				},
  				to: {
  					height: 'var(--radix-accordion-content-height)'
  				}
  			},
  			'accordion-up': {
  				from: {
  					height: 'var(--radix-accordion-content-height)'
  				},
  				to: {
  					height: 0
  				}
  			},
  			'collapsible-down': {
  				from: {
  					height: 0
  				},
  				to: {
  					height: 'var(--radix-collapsible-content-height)'
  				}
  			},
  			'collapsible-up': {
  				from: {
  					height: 'var(--radix-collapsible-content-height)'
  				},
  				to: {
  					height: 0
  				}
  			}
  		},
  		animation: {
  			'accordion-down': 'accordion-down 0.2s ease-out',
  			'accordion-up': 'accordion-up 0.2s ease-out',
  			'collapsible-down': 'collapsible-down 0.2s ease-in-out',
  			'collapsible-up': 'collapsible-up 0.2s ease-in-out'
  		}
  	}
  },
  plugins: [
    require('@tailwindcss/typography'),
    animate,
      require("tailwindcss-animate")
],
}
