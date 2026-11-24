// AudioWorklet that hands the captured microphone samples to the page in blocks. It only copies samples into memory
// (nothing is stored, nothing is sent): the page decides what to do with them. Served from the page's own origin.
class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super()
    this.buffer = new Float32Array(2048) // ~43 ms at 48 kHz: ~23 level updates per second
    this.filled = 0
    this.port.onmessage = (event) => {
      if (event.data === 'flush') {
        this.post()
        this.port.postMessage({ flushed: true })
      }
    }
  }

  post() {
    if (this.filled === 0) return
    const pcm = this.buffer.slice(0, this.filled)
    this.filled = 0
    this.port.postMessage({ pcm }, [pcm.buffer])
  }

  process(inputs) {
    const channels = inputs[0]
    if (!channels || channels.length === 0) return true
    const frames = channels[0].length
    for (let i = 0; i < frames; i++) {
      let sum = 0
      for (let c = 0; c < channels.length; c++) sum += channels[c][i] // mono mix of whatever the device gives
      this.buffer[this.filled++] = sum / channels.length
      if (this.filled === this.buffer.length) this.post()
    }
    return true
  }
}

registerProcessor('pcm-capture', PcmCapture)
