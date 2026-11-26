export const styles = [
  {
    name: 'default',
    label: 'Default',
  },
  {
    name: 'new-york',
    label: 'New York',
  },
  {
    name: 'lyra',
    label: 'Lyra',
  },
] as const

export type Style = typeof styles[number]['name']
