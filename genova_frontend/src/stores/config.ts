import { type Style } from '@/lib/registry/styles'
import { type Theme, themes } from '@/lib/registry/themes'
import { useColorMode, useStorage } from '@vueuse/core'
import { computed } from 'vue'

interface Config {
  theme?: Theme['name']
  radius: number
  style: Style
}


export function useConfigStore() {
  const mode = useColorMode()
  const isDark = computed(() => mode.value === 'dark')

  const config = useStorage<Config>('config', {
    theme: 'blue',
    radius: 0,
    style: 'lyra',
  })

  const themeClass = computed(() => `theme-${config.value.theme}`)

  const theme = computed(() => config.value.theme)
  const radius = computed(() => config.value.radius)
  const style = computed(() => config.value.style)

  function setTheme(themeName: Theme['name']) {
    config.value.theme = themeName
  }

  function setRadius(value: number) {
    config.value.radius = value
  }

  const themePrimary = computed(() => {
    const t = themes.find(t => t.name === theme.value)
    return `hsl(${
      t?.cssVars[isDark ? 'dark' : 'light'].primary
    })`
  })

  return {
    config,
    theme,
    setTheme,
    radius,
    setRadius,
    themeClass,
    style,
    themePrimary,
  }
}
