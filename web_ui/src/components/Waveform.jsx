import { useEffect, useRef } from 'react';

export default function Waveform({ isRecording, stream }) {
  const canvasRef = useRef(null);
  const animationRef = useRef(null);
  const audioCtxRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    
    // High DPI fix
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.offsetWidth * dpr;
    canvas.height = canvas.offsetHeight * dpr;
    ctx.scale(dpr, dpr);

    let analyzer;
    let dataArray;

    if (isRecording && stream) {
      if (!audioCtxRef.current) {
        audioCtxRef.current = new (window.AudioContext || window.webkitAudioContext)();
      }
      const audioCtx = audioCtxRef.current;
      const source = audioCtx.createMediaStreamSource(stream);
      analyzer = audioCtx.createAnalyser();
      analyzer.fftSize = 64; // Smaller FFT for cleaner bar look
      source.connect(analyzer);
      dataArray = new Uint8Array(analyzer.frequencyBinCount);
    } else {
      dataArray = new Uint8Array(32).fill(0);
    }

    const draw = () => {
      animationRef.current = requestAnimationFrame(draw);
      
      const w = canvas.offsetWidth;
      const h = canvas.offsetHeight;
      ctx.clearRect(0, 0, w, h);
      
      if (analyzer) {
        analyzer.getByteFrequencyData(dataArray);
      } else {
        // Idle pulse effect
        for(let i=0; i<dataArray.length; i++) {
          dataArray[i] = Math.sin(Date.now() / 200 + i) * 5 + 5;
        }
      }

      const barCount = 32;
      const barWidth = (w / barCount) - 2;
      const accentColor = isRecording ? '#ff3b30' : '#00e5ff';
      
      for (let i = 0; i < barCount; i++) {
        const val = dataArray[i] || 0;
        const barHeight = (val / 255) * h * 0.8 + 2;
        const x = i * (barWidth + 2);
        const y = (h - barHeight) / 2;

        // Draw Glow
        ctx.shadowBlur = isRecording ? 15 : 10;
        ctx.shadowColor = accentColor;
        
        // Draw Bar
        const grad = ctx.createLinearGradient(x, y, x, y + barHeight);
        grad.addColorStop(0, accentColor);
        grad.addColorStop(1, 'rgba(0, 229, 255, 0)');
        
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.roundRect(x, y, barWidth, barHeight, 2);
        ctx.fill();
      }
    };

    draw();

    return () => {
      cancelAnimationFrame(animationRef.current);
    };
  }, [isRecording, stream]);

  return <canvas ref={canvasRef} style={{ width: '100%', height: '100%' }} />;
}
