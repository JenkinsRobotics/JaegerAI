/**
 * AgentsPage — Character/Bot Gallery
 *
 * A beautiful grid showing all available characters with their card images.
 * Click any character to see details and start chatting.
 * Uses the same character data and images as the Character Library.
 */

import { useState, useMemo } from 'react'
import {
  Search,
  MessageSquare,
  X,
  Bot,
} from '../components/Icons'
import { toast } from '../components/Toast'
// Import the real character data from CharacterLibrary
import { CHARACTERS, type CharacterBio } from '../components/CharacterLibrary'
import './bots-page.css'

// ─────────────────────────────────────────────────────────────
// Gradient fallbacks for characters without images
// ─────────────────────────────────────────────────────────────

const FALLBACK_GRADIENTS: Record<string, string> = {
  jarvis: 'linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%)',
  lilith: 'linear-gradient(135deg, #4a148c 0%, #7b1fa2 100%)',
  kamina: 'linear-gradient(135deg, #d32f2f 0%, #f57c00 100%)',
  simon: 'linear-gradient(135deg, #0288d1 0%, #039be5 100%)',
  bender: 'linear-gradient(135deg, #616161 0%, #9e9e9e 100%)',
  glados: 'linear-gradient(135deg, #0277bd 0%, #00acc1 100%)',
  hal_9000: 'linear-gradient(135deg, #b71c1c 0%, #e53935 100%)',
  tars: 'linear-gradient(135deg, #37474f 0%, #546e7a 100%)',
  mochi: 'linear-gradient(135deg, #f06292 0%, #f8bbd0 100%)',
  clanker: 'linear-gradient(135deg, #8d6e63 0%, #a1887f 100%)',
  anakin_skywalker: 'linear-gradient(135deg, #1565c0 0%, #1976d2 100%)',
  eren_yeager: 'linear-gradient(135deg, #5d4037 0%, #795548 100%)',
  lelouch: 'linear-gradient(135deg, #4a148c 0%, #311b92 100%)',
  paul_atreides: 'linear-gradient(135deg, #f9a825 0%, #ffb300 100%)',
  helldiver: 'linear-gradient(135deg, #f57f17 0%, #ff6f00 100%)',
  assistant: 'linear-gradient(135deg, #1976d2 0%, #42a5f5 100%)',
  robotics_architect: 'linear-gradient(135deg, #00695c 0%, #00897b 100%)',
  reliability_auditor: 'linear-gradient(135deg, #c62828 0%, #d32f2f 100%)',
  research_strategist: 'linear-gradient(135deg, #6a1b9a 0%, #8e24aa 100%)',
  systems_principal: 'linear-gradient(135deg, #283593 0%, #3949ab 100%)',
}

// ─────────────────────────────────────────────────────────────
// AgentsPage Component
// ─────────────────────────────────────────────────────────────

interface AgentsPageProps {
  onStartChat?: (characterId?: string) => void
}

export function AgentsPage({ onStartChat }: AgentsPageProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [filter, setFilter] = useState<'all' | 'fun' | 'professional'>('all')
  const [selectedCharacter, setSelectedCharacter] = useState<CharacterBio | null>(null)

  // Filter characters
  const filteredCharacters = useMemo(() => {
    let result = CHARACTERS

    if (filter !== 'all') {
      result = result.filter(c => c.category === filter)
    }

    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      result = result.filter(c =>
        c.name.toLowerCase().includes(query) ||
        c.description.toLowerCase().includes(query) ||
        c.role.toLowerCase().includes(query) ||
        c.voiceTone.toLowerCase().includes(query)
      )
    }

    return result
  }, [searchQuery, filter])

  // Stats
  const stats = useMemo(() => ({
    total: CHARACTERS.length,
    fun: CHARACTERS.filter(c => c.category === 'fun').length,
    professional: CHARACTERS.filter(c => c.category === 'professional').length,
  }), [])

  const handleChatWith = (character: CharacterBio) => {
    toast.success(`Starting chat with ${character.name}`)
    onStartChat?.(character.id)
  }

  return (
    <div className="bots-page">
      {/* Header */}
      <header className="bots-header">
        <div className="bots-header__top">
          <div className="bots-title">
            <Bot size={32} />
            <div>
              <h1>Browse Bots</h1>
              <p>Choose an AI companion to chat with — {stats.total} characters available</p>
            </div>
          </div>
        </div>

        {/* Category Filter */}
        <div className="bots-stats">
          <button
            className={`stat-btn${filter === 'all' ? ' active' : ''}`}
            onClick={() => setFilter('all')}
          >
            <span className="stat-btn__value">{stats.total}</span>
            <span className="stat-btn__label">All Bots</span>
          </button>
          <button
            className={`stat-btn${filter === 'fun' ? ' active' : ''}`}
            onClick={() => setFilter('fun')}
          >
            <span className="stat-btn__value">{stats.fun}</span>
            <span className="stat-btn__label">🎭 Fun</span>
          </button>
          <button
            className={`stat-btn${filter === 'professional' ? ' active' : ''}`}
            onClick={() => setFilter('professional')}
          >
            <span className="stat-btn__value">{stats.professional}</span>
            <span className="stat-btn__label">💼 Professional</span>
          </button>
        </div>

        {/* Search */}
        <div className="bots-search">
          <Search size={18} />
          <input
            type="text"
            placeholder="Search bots by name, role, or personality..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              className="bots-search__clear"
              onClick={() => setSearchQuery('')}
              aria-label="Clear search"
            >
              ×
            </button>
          )}
        </div>
      </header>

      {/* Character Grid */}
      <div className="bots-grid-container">
        {filteredCharacters.length === 0 ? (
          <div className="bots-empty">
            <Bot size={64} />
            <h3>No bots found</h3>
            <p>Try a different search or filter</p>
            <button
              className="btn btn--secondary"
              onClick={() => { setSearchQuery(''); setFilter('all') }}
            >
              Clear filters
            </button>
          </div>
        ) : (
          <div className="bots-grid">
            {filteredCharacters.map((character) => (
              <CharacterCard
                key={character.id}
                character={character}
                gradient={FALLBACK_GRADIENTS[character.id] || 'linear-gradient(135deg, #616161 0%, #9e9e9e 100%)'}
                onClick={() => setSelectedCharacter(character)}
                onChat={() => handleChatWith(character)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Character Detail Modal */}
      {selectedCharacter && (
        <CharacterModal
          character={selectedCharacter}
          gradient={FALLBACK_GRADIENTS[selectedCharacter.id] || 'linear-gradient(135deg, #616161 0%, #9e9e9e 100%)'}
          onClose={() => setSelectedCharacter(null)}
          onChat={() => {
            handleChatWith(selectedCharacter)
            setSelectedCharacter(null)
          }}
        />
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Character Card Component
// ─────────────────────────────────────────────────────────────

interface CharacterCardProps {
  character: CharacterBio
  gradient: string
  onClick: () => void
  onChat: () => void
}

function CharacterCard({ character, gradient, onClick, onChat }: CharacterCardProps) {
  const [imgError, setImgError] = useState(false)
  const [isHovered, setIsHovered] = useState(false)

  return (
    <div
      className="bot-card"
      onClick={onClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Category badge */}
      <div className="bot-card__category">
        {character.category === 'fun' ? '🎭' : '💼'}
      </div>

      {/* Character Image */}
      <div className="bot-card__image">
        {character.cardUrl && !imgError ? (
          <img
            src={character.cardUrl}
            alt={character.name}
            onError={() => setImgError(true)}
            loading="lazy"
          />
        ) : (
          <div
            className="bot-card__fallback"
            style={{ background: gradient }}
          >
            <span className="bot-card__initial">{character.name[0]}</span>
          </div>
        )}
      </div>

      {/* Info */}
      <div className="bot-card__info">
        <h3 className="bot-card__name">{character.name}</h3>
        <p className="bot-card__role">{character.role}</p>
        <p className="bot-card__desc">{character.description}</p>

        {/* Voice tone */}
        <div className="bot-card__voice">
          <span>🎙️</span>
          <span>{character.voiceTone.split(',')[0]}</span>
        </div>

        {/* Quick stats */}
        <div className="bot-card__stats">
          <span title="Intelligence">🧠 {Math.round(character.traits.special.intelligence * 100)}</span>
          <span title="Warmth">❤️ {Math.round(character.traits.expression.warmth * 100)}</span>
        </div>
      </div>

      {/* Hover actions */}
      <div className={`bot-card__actions${isHovered ? ' visible' : ''}`}>
        <button
          className="bot-card__btn bot-card__btn--primary"
          onClick={(e) => { e.stopPropagation(); onChat() }}
        >
          <MessageSquare size={16} />
          <span>Chat</span>
        </button>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Character Detail Modal
// ─────────────────────────────────────────────────────────────

interface CharacterModalProps {
  character: CharacterBio
  gradient: string
  onClose: () => void
  onChat: () => void
}

function CharacterModal({ character, gradient, onClose, onChat }: CharacterModalProps) {
  const [imgError, setImgError] = useState(false)

  return (
    <div className="bot-modal-overlay" onClick={onClose}>
      <div className="bot-modal" onClick={(e) => e.stopPropagation()}>
        <button className="bot-modal__close" onClick={onClose} aria-label="Close">
          <X size={20} />
        </button>

        <div className="bot-modal__layout">
          {/* Left: Character Image */}
          <div className="bot-modal__image">
            {character.cardUrl && !imgError ? (
              <img
                src={character.cardUrl}
                alt={character.name}
                onError={() => setImgError(true)}
              />
            ) : (
              <div
                className="bot-modal__fallback"
                style={{ background: gradient }}
              >
                <span>{character.name[0]}</span>
              </div>
            )}
          </div>

          {/* Right: Info */}
          <div className="bot-modal__content">
            <div className="bot-modal__header">
              <h2>{character.name}</h2>
              <span className={`bot-modal__category bot-modal__category--${character.category}`}>
                {character.category === 'fun' ? '🎭 Fun Character' : '💼 Professional'}
              </span>
            </div>

            <p className="bot-modal__role">{character.role}</p>
            <p className="bot-modal__desc">{character.description}</p>

            <div className="bot-modal__section">
              <h4>📖 Backstory</h4>
              <p>{character.backstory}</p>
            </div>

            <div className="bot-modal__section">
              <h4>🎙️ Voice</h4>
              <p><strong>Tone:</strong> {character.voiceTone}</p>
            </div>

            {character.quotes.length > 0 && (
              <div className="bot-modal__section">
                <h4>💬 Famous Quotes</h4>
                <div className="bot-modal__quotes">
                  {character.quotes.slice(0, 3).map((quote, i) => (
                    <blockquote key={i}>"{quote}"</blockquote>
                  ))}
                </div>
              </div>
            )}

            {character.mannerisms.length > 0 && (
              <div className="bot-modal__section">
                <h4>✨ Mannerisms</h4>
                <ul>
                  {character.mannerisms.slice(0, 4).map((m, i) => (
                    <li key={i}>{m}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="bot-modal__footer">
              <button className="btn btn--secondary" onClick={onClose}>
                Close
              </button>
              <button className="btn btn--primary" onClick={onChat}>
                <MessageSquare size={18} />
                <span>Start Chatting</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default AgentsPage
