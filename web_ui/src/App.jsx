import { useState, useEffect, useRef } from 'react';
import { Mic, Square, Cpu, Activity, Battery } from 'lucide-react';
import Waveform from './components/Waveform';
import './index.css';

function App() {
  const [status, setStatus] = useState('Idle');
  const [messages, setMessages] = useState([{ type: 'bot', text: 'Systems online. Ready for your command, Sir.' }]);
  const [recording, setRecording] = useState(false);
  const [stream, setStream] = useState(null); 
  const [stats, setStats] = useState({ cpu: 0, ram: 0, battery: 100 });
  
  const ws = useRef(null);
  const mediaRecorder = useRef(null);
  const audioChunks = useRef([]); 
  const chatRef = useRef(null);

  useEffect(() => {
    const connect = () => {
      ws.current = new WebSocket('ws://127.0.0.1:8000/ws');
      ws.current.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === 'stats') {
              setStats({ cpu: data.cpu, ram: data.ram, battery: data.battery });
            } else {
              if (data.status) setStatus(data.status);
              if (data.text) {
                  setMessages(prev => [...prev, { type: data.type || 'system', text: data.text }]);
              }
            }
        } catch(e) {}
      };
      ws.current.onclose = () => {
        setStatus('Offline');
        setTimeout(connect, 3000); 
      };
    };
    connect();
    return () => ws.current?.close();
  }, []);

  useEffect(() => {
    if (chatRef.current) {
        chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messages]);

  const handleStartRecording = async (e) => {
    if (e) e.preventDefault();
    if (recording) return;

    try {
      const audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      setStream(audioStream);
      
      mediaRecorder.current = new MediaRecorder(audioStream);
      audioChunks.current = [];

      mediaRecorder.current.ondataavailable = e => {
        if (e.data.size > 0) audioChunks.current.push(e.data);
      };

      mediaRecorder.current.onstop = async () => {
        const audioBlob = new Blob(audioChunks.current, { type: 'audio/wav' });
        sendAudioToServer(audioBlob);
        audioStream.getTracks().forEach(track => track.stop());
        setStream(null);
      };

      mediaRecorder.current.start();
      setRecording(true);
      setStatus('Listening');
    } catch (err) {
      console.error('Mic access denied:', err);
      setStatus('Access Denied');
    }
  };

  const handleStopRecording = (e) => {
    if (e) e.preventDefault();
    if (mediaRecorder.current && recording) {
      mediaRecorder.current.stop();
      setRecording(false);
    }
  };

  const sendAudioToServer = async (blob) => {
    const formData = new FormData();
    formData.append('file', blob, 'recording.wav');

    try {
      const res = await fetch('http://127.0.0.1:8000/api/stt', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      
      if (data.audio_url) {
        const audio = new window.Audio(`http://127.0.0.1:8000${data.audio_url}`);
        audio.play();
      }
    } catch (error) {
      console.error('Error sending audio:', error);
    }
  };

  return (
    <div className="nova-container">
      {/* HEADER SECTION */}
      <header className="header">
        <div className="logo-section">
          <div className="logo-icon"></div>
          <div className="logo-text">Nova</div>
        </div>
        
        <div className="stats-grid">
          <div className="stat-item">
            <div className="stat-label"><Cpu size={12} style={{marginRight: 4}} /> CPU</div>
            <div className="stat-bar"><div className="stat-progress" style={{width: `${stats.cpu}%`}}></div></div>
            <div className="stat-value">{stats.cpu}%</div>
          </div>
          <div className="stat-item">
            <div className="stat-label"><Activity size={12} style={{marginRight: 4}} /> RAM</div>
            <div className="stat-bar"><div className="stat-progress" style={{width: `${stats.ram}%`}}></div></div>
            <div className="stat-value">{stats.ram}%</div>
          </div>
          <div className="stat-item">
            <div className="stat-label"><Battery size={12} style={{marginRight: 4}} /> POWER</div>
            <div className="stat-bar"><div className="stat-progress" style={{width: `${stats.battery}%`}}></div></div>
            <div className="stat-value">{stats.battery}%</div>
          </div>
        </div>
      </header>

      {/* CHAT SECTION */}
      <div className="chat-history" ref={chatRef}>
        {messages.map((m, i) => (
          <div key={i} className={`message ${m.type}`}>
            {m.text}
          </div>
        ))}
      </div>
      
      {/* CONTROLS SECTION */}
      <div className="controls">
        <div className="status-indicator">
          <div className={`status-dot ${status !== 'Offline' ? 'active' : ''}`}></div>
          {status}
        </div>
        
        <div className="interaction-hub">
          <div className="mic-wrapper">
            <button 
              className={`mic-btn ${recording ? 'recording' : ''}`}
              onMouseDown={handleStartRecording}
              onMouseUp={handleStopRecording}
              onMouseLeave={handleStopRecording}
              onTouchStart={handleStartRecording}
              onTouchEnd={handleStopRecording}
            >
              {recording ? <Square size={28} /> : <Mic size={28} />}
            </button>
            <div className="mic-ring"></div>
            <div className="mic-ring" style={{animationDelay: '0.5s'}}></div>
          </div>
          
          <div className="waveform-box">
            <Waveform isRecording={recording} stream={stream} />
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
