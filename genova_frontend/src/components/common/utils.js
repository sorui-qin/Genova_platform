
export async function init_ketcher_module(domId) {
  let ketcher_name = 'ketcher'
  if (domId === 'idKetcher') {
    ketcher_name = 'ketcher'
  } else {
    ketcher_name = 'ketcher' + domId
  }
  try {
    for (let i = 0; i < 1000; i++) {
      const ketcherFrame = document.getElementById(domId)

      if ('contentDocument' in ketcherFrame) {
        window[ketcher_name] = ketcherFrame.contentWindow.ketcher
      } else {
        window[ketcher_name] = document.frames[domId].window.ketcher
      }
      if (window[ketcher_name]) {
        return true
      } else {
        console.log('ketcher wait!')
        await sleep(100)
      }
    }
    return false
  } catch {
    console.log('wait ketcher')
  }
}

export const sleep = (delaytime = 1000) => {
  return new Promise(resolve => setTimeout(resolve, delaytime))
}