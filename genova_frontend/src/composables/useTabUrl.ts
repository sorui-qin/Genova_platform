import { ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

export interface TabConfig {
  value: string
  urlParam: string
}

export function useTabUrl(tabConfigs: TabConfig[], defaultTab: string = 'create') {
  const route = useRoute()
  const router = useRouter()
  const activeTab = ref(defaultTab)

  // Create mapping objects for quick lookup
  const valueToUrlParam = new Map<string, string>()
  const urlParamToValue = new Map<string, string>()
  
  tabConfigs.forEach(config => {
    valueToUrlParam.set(config.value, config.urlParam)
    urlParamToValue.set(config.urlParam, config.value)
  })

  // Initialize activeTab from URL query parameter
  const initializeTabFromUrl = () => {
    const tabQuery = route.query.tab as string
    const validUrlParams = tabConfigs.map(config => config.urlParam)
    
    if (tabQuery && validUrlParams.includes(tabQuery)) {
      const tabValue = urlParamToValue.get(tabQuery)
      if (tabValue) {
        activeTab.value = tabValue
      }
    } else if (!tabQuery) {
      // If no tab query parameter, set default and update URL
      updateTabUrl(defaultTab)
    }
  }

  // Method to update URL when tab changes
  const updateTabUrl = (tabValue: string) => {
    const urlParam = valueToUrlParam.get(tabValue)
    if (urlParam) {
      router.push({
        query: { ...route.query, tab: urlParam }
      })
    }
  }

  // Method to handle tab click
  const handleTabClick = (tabValue: string) => {
    activeTab.value = tabValue
    updateTabUrl(tabValue)
  }

  // Watch for route changes to sync activeTab
  watch(() => route.query.tab, (newTab) => {
    if (newTab && typeof newTab === 'string') {
      const tabValue = urlParamToValue.get(newTab)
      if (tabValue) {
        activeTab.value = tabValue
      }
    }
  })

  // Initialize on mount
  onMounted(() => {
    initializeTabFromUrl()
  })

  return {
    activeTab,
    handleTabClick,
    updateTabUrl,
    initializeTabFromUrl
  }
}

// Predefined tab configurations for common use cases
export const STANDARD_TAB_CONFIGS: TabConfig[] = [
  { value: 'create', urlParam: 'submit_task' },
  { value: 'results', urlParam: 'recent_results' },
  { value: 'examples', urlParam: 'examples' },
  { value: 'documentation', urlParam: 'documentation' }
] 