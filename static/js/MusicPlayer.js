const { useState, useRef, useEffect } = React;

function MusicPlayer() {
  const [selectedOption, setSelectedOption] = useState('');
  const [isPlaying, setIsPlaying] = useState(false);
  const [volume, setVolume] = useState(0.5);
  const [customFile, setCustomFile] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [currentTrack, setCurrentTrack] = useState(null);

  const LASTFM_API_KEY = '631ff82cb57afc3da0308aebf9c45939';
  const audioRef = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    if (customFile) {
      return () => URL.revokeObjectURL(customFile);
    }
  }, [customFile]);

  const handleOptionChange = (e) => {
    const option = e.target.value;
    setSelectedOption(option);
    setIsPlaying(false);
    setCustomFile(null); // Reset custom file when changing options
    setSearchQuery('');
    setSearchResults([]);
    setCurrentTrack(null);
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
  };

  const handleSearchChange = (e) => {
    setSearchQuery(e.target.value);
  };

  const handleSearchSubmit = async () => {
    try {
      const response = await fetch(
        `https://ws.audioscrobbler.com/2.0/?method=track.search&track=${encodeURIComponent(searchQuery)}&api_key=${LASTFM_API_KEY}&format=json`
      );
      const data = await response.json();
      const tracks = data.results && data.results.trackmatches && data.results.trackmatches.track ? data.results.trackmatches.track : [];
      setSearchResults(tracks.slice(0, 5)); // Limit to 5 results
    } catch (error) {
      console.error('Search error:', error);
    }
  };

  const handleTrackSelect = (track) => {
    setCurrentTrack(track);
    setIsPlaying(true);
  };

  const handlePlay = () => {
    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause();
      } else {
        audioRef.current.play();
      }
      setIsPlaying(!isPlaying);
    }
  };

  const handleVolumeChange = (e) => {
    const newVolume = parseFloat(e.target.value);
    setVolume(newVolume);
    if (audioRef.current) {
      audioRef.current.volume = newVolume;
    }
  };

  const handleFileUpload = (e) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      const file = files[0]; // Get the first file
      setCustomFile(URL.createObjectURL(file));
    }
  };

  const handleFileButtonClick = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const getAudioSource = () => {
    switch (selectedOption) {
      case 'brown-noise':
        return '/static/brown-noise.mp3';
      case 'binaural-beats':
        return '/static/binaural-beats.mp3';
      case 'import':
        return customFile;
    }
  };

  return (
    <div className="card mb-4">
      <div className="card-header d-flex justify-content-between align-items-center">
        <h5 className="card-title mb-0">
          <i className="bi bi-volume-up me-2"></i> Music Player
        </h5>
      </div>
      <div className="card-body">
        <div className="mb-4">
          <select className="form-select mb-3" value={selectedOption} onChange={handleOptionChange}>
            <option value="">Select Audio Source</option>
            <option value="brown-noise">Brown Noise</option>
            <option value="binaural-beats">Binaural Beats</option>
            <option value="import">Import Audio</option>
          </select>
          {selectedOption === 'import' && (
            <div className="mb-3">
              <button className="btn btn-outline-primary w-100" onClick={handleFileButtonClick}>
                <i className="bi bi-cloud-upload me-2"></i> Upload Audio File
              </button>
              <input ref={fileInputRef} type="file" accept="audio/*" className="d-none" onChange={handleFileUpload} />
            </div>
          )}
          {selectedOption && selectedOption !== 'online' && (
            <div className="d-flex flex-column gap-3">
              <audio ref={audioRef} src={getAudioSource()} onEnded={() => setIsPlaying(false)} />
              <div className="d-flex align-items-center justify-content-center gap-3">
              <button
                  className={`btn ${isPlaying ? 'btn-danger' : 'btn-primary'}`}
                  onClick={handlePlay}
                >
                  <i className={`bi ${isPlaying ? 'bi-pause' : 'bi-play'}`}></i>
                </button>
                <div className="d-flex align-items-center gap-2 flex-grow-1">
                  <i className="bi bi-volume-up"></i>
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.01"
                    value={volume}
                    onChange={handleVolumeChange}
                    className="form-range"
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const container = document.getElementById('music-player');
if (!container) {
  console.log('Container element does not exist, waiting...');
  setTimeout(() => {
    const container = document.getElementById('music-player');
    if (container) {
      console.log('Container element exists');
      ReactDOM.render(<MusicPlayer />, container);
      console.log('Component has been rendered');
    } else {
      console.log('Container element still does not exist');
    }
  }, 1000);
} else {
  console.log('Container element exists');
  ReactDOM.render(<MusicPlayer />, container);
}
