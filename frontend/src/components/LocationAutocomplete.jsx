import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { MapPin, Loader, Mountain, Waves, Building2, Landmark, TreePine } from 'lucide-react';
import { API_URL } from '../constants';

const TYPE_ICONS = {
  city: Building2,
  beach: Waves,
  'hill-station': Mountain,
  landmark: Landmark,
  spiritual: TreePine,
  state: MapPin,
  country: MapPin,
  island: Waves,
};

const LocationAutocomplete = ({
  value,
  onChange,
  onSelect,
  placeholder = 'Search destination...',
  testId,
  className = '',
}) => {
  const [suggestions, setSuggestions] = useState([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [loading, setLoading] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const debounceRef = useRef(null);
  const wrapperRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleChange = (e) => {
    const newValue = e.target.value;
    onChange(newValue);

    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (newValue.trim().length < 3) {
      setSuggestions([]);
      setShowDropdown(false);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const response = await axios.get(
          `${API_URL}/locations/autocomplete?q=${encodeURIComponent(newValue)}`,
          { withCredentials: true }
        );
        setSuggestions(response.data.suggestions || []);
        setShowDropdown(true);
        setHighlightedIndex(-1);
      } catch (error) {
        console.error('Autocomplete error:', error);
      } finally {
        setLoading(false);
      }
    }, 250);
  };

  const handleSelect = (suggestion) => {
    onChange(suggestion.display_name);
    if (onSelect) onSelect(suggestion);
    setShowDropdown(false);
    setSuggestions([]);
  };

  const handleKeyDown = (e) => {
    if (!showDropdown || suggestions.length === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlightedIndex((prev) => Math.min(prev + 1, suggestions.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightedIndex((prev) => Math.max(prev - 1, -1));
    } else if (e.key === 'Enter' && highlightedIndex >= 0) {
      e.preventDefault();
      handleSelect(suggestions[highlightedIndex]);
    } else if (e.key === 'Escape') {
      setShowDropdown(false);
    }
  };

  return (
    <div ref={wrapperRef} className={`relative ${className}`}>
      <div className="flex items-center gap-2 border border-[#E7E5E4] rounded-lg px-4 py-3 bg-white focus-within:border-[#C47245] transition-colors">
        <MapPin size={20} className="text-[#57534E] flex-shrink-0" />
        <input
          data-testid={testId}
          type="text"
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onFocus={() => value && value.length >= 3 && suggestions.length > 0 && setShowDropdown(true)}
          placeholder={placeholder}
          autoComplete="off"
          className="flex-1 outline-none bg-transparent text-[#1C1917] placeholder-[#A8A29E]"
        />
        {loading && <Loader size={16} className="text-[#C47245] animate-spin" />}
      </div>

      {showDropdown && suggestions.length > 0 && (
        <div className="absolute z-50 left-0 right-0 mt-1 bg-white border border-[#E7E5E4] rounded-lg shadow-xl overflow-hidden max-h-80 overflow-y-auto">
          {suggestions.map((suggestion, idx) => {
            const Icon = TYPE_ICONS[suggestion.type] || MapPin;
            return (
              <button
                key={`${suggestion.name}-${idx}`}
                data-testid={`${testId}-suggestion-${idx}`}
                type="button"
                onClick={() => handleSelect(suggestion)}
                onMouseEnter={() => setHighlightedIndex(idx)}
                className={`w-full text-left px-4 py-3 flex items-center gap-3 transition-colors border-b border-[#F5F2EB] last:border-b-0 ${
                  highlightedIndex === idx ? 'bg-[#C47245]/10' : 'hover:bg-[#F5F2EB]'
                }`}
              >
                <div className="bg-[#C47245]/10 p-2 rounded-lg flex-shrink-0">
                  <Icon size={18} className="text-[#C47245]" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-[#1C1917] truncate">{suggestion.name}</div>
                  <div className="text-xs text-[#57534E] flex items-center gap-2">
                    <span>{suggestion.country}</span>
                    <span className="bg-[#F5F2EB] px-2 py-0.5 rounded text-[10px] uppercase tracking-wider">
                      {suggestion.type.replace('-', ' ')}
                    </span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {showDropdown && !loading && suggestions.length === 0 && value.length >= 3 && (
        <div className="absolute z-50 left-0 right-0 mt-1 bg-white border border-[#E7E5E4] rounded-lg shadow-xl px-4 py-3 text-sm text-[#57534E]">
          No popular destinations match. Type the full location name and we'll find it.
        </div>
      )}
    </div>
  );
};

export default LocationAutocomplete;
