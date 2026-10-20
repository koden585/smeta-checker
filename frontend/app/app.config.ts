export default defineAppConfig({
  ui: {
    colors: {
      primary: 'orange',
      neutral: 'zinc',
      success: 'green',
      warning: 'amber',
      error: 'red',
      info: 'blue',
    },
    button: {
      slots: { base: 'min-h-11 min-w-11 justify-center font-semibold' },
      defaultVariants: { size: 'md' },
    },
    input: { slots: { base: 'min-h-11 text-base' } },
    select: { slots: { base: 'min-h-11 text-base' } },
  },
})
