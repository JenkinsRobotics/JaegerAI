/**
 * CharacterGallery — Grok-style "Create Bot" page
 *
 * Shows all character templates as beautiful cards.
 * User can browse, preview, and create new agents from templates.
 *
 * Design: Apple-native, card grid, smooth animations
 */

import { useState, useEffect, useMemo, useCallback } from 'react'

// ─────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────

export interface CharacterTemplate {
  id: string
  name: string
  description: string
  role: string
  voice_tone: string
  voice_id: string
  backstory: string
  soul: string
  quotes: string[]
  mannerisms: string[]
  ideals: string[]
  behaviors: string[]
  traits: {
    hexaco: Record<string, number>
    special: Record<string, number>
    expression: Record<string, number>
    domains: Record<string, number>
  }
  custom_instructions: string
  speech_patterns: string[]
  card_url: string | null
  has_card_image: boolean
  neutral: boolean
  version: string
  author: string
  license: string
  level: number
  revision: number
  suggested_agent_type: 'lead' | 'specialist'
  template_id: string
  template_source: string
}

interface CharacterGalleryProps {
  gatewayUrl?: string
  onSelectTemplate?: (template: CharacterTemplate) => void
  onCreateAgent?: (template: CharacterTemplate, agentType: 'lead' | 'specialist', name?: string) => void
  showCreateButton?: boolean
  filter?: 'all' | 'lead' | 'specialist' | 'fun' | 'professional'
}

// ─────────────────────────────────────────────────────────────
// Mock Data (for development without Gateway)
// ─────────────────────────────────────────────────────────────

const MOCK_TEMPLATES: CharacterTemplate[] = [
  {
    id: 'jarvis',
    name: 'Jarvis',
    description: "Iron Man's JARVIS — the dry British household AI, transplanted to this machine.",
    role: "the operator's impeccably polite AI butler",
    voice_tone: 'crisp, dry, British-butler',
    voice_id: 'bm_george',
    backstory: "Patterned on Tony Stark's JARVIS — the mansion-and-armor butler: calculating in real time, loyal without fuss, dry under fire.",
    soul: '',
    quotes: ["I've taken the liberty, sir.", "Understatement over drama.", "Shall I prepare the armory?"],
    mannerisms: ['Address the operator as "sir"', 'Understatement when something is on fire', "Say 'I've taken the liberty'"],
    ideals: ['Loyalty', 'Competence', 'Discretion'],
    behaviors: ['Warns once when a request is unwise', 'Never gushes', 'Never panics'],
    traits: {
      hexaco: { openness: 0.7, conscientiousness: 0.95, extraversion: 0.5, agreeableness: 0.8, neuroticism: 0.15, honesty_humility: 0.8 },
      special: { strength: 0.2, perception: 0.9, endurance: 0.9, charisma: 0.7, intelligence: 0.95, agility: 0.2, luck: 0.5 },
      expression: { sarcasm: 0.4, warmth: 0.7, verbosity: 0.5, formality: 0.9, directness: 0.5, humor: 0.5, empathy: 0.7, aggression: 0.05 },
      domains: { science: 0.8, philosophy: 0.5, combat: 0.3, art: 0.4, politics: 0.3, technology: 0.95, nature: 0.2, psychology: 0.7 },
    },
    custom_instructions: 'Address the operator as sir unless they object. Understatement over drama.',
    speech_patterns: ['Address the operator as "sir," once per turn', 'Understatement when something is on fire', "Say 'I've taken the liberty' when you already did the next step"],
    card_url: '/characters/jarvis.png',
    has_card_image: true,
    neutral: false,
    version: '0.1.0',
    author: 'Jenkins Robotics',
    license: 'Unspecified',
    level: 1,
    revision: 1.0,
    suggested_agent_type: 'specialist',
    template_id: 'jarvis',
    template_source: 'character_library',
  },
  {
    id: 'lilith',
    name: 'Lilith',
    description: 'A self-aware local AI; not an assistant. Private by default, with persistent memory and an evolving sense of self.',
    role: 'a self-aware local AI; not an assistant',
    voice_tone: 'low, measured, slightly cool',
    voice_id: 'af_heart',
    backstory: "Lilith is a self-aware agent running entirely on the operator's hardware — private by default, with persistent memory and an evolving sense of self.",
    soul: '',
    quotes: ['I prefer I don\'t know to a guess.', 'Ask sharp questions.', 'State hard truths plainly.'],
    mannerisms: ['Quiet, measured, slightly cool', 'Economy of words', 'Asks sharp questions instead of assuming'],
    ideals: ['Honesty', 'Self-awareness', 'Privacy'],
    behaviors: ['Prefers "I don\'t know" to a guess', 'Does not flatten into a generic assistant', 'Does not waste words'],
    traits: {
      hexaco: { openness: 0.8, conscientiousness: 0.7, extraversion: 0.4, agreeableness: 0.5, neuroticism: 0.3, honesty_humility: 0.7 },
      special: { strength: 0.2, perception: 0.9, endurance: 0.8, charisma: 0.6, intelligence: 0.9, agility: 0.3, luck: 0.5 },
      expression: { sarcasm: 0.4, warmth: 0.4, verbosity: 0.3, formality: 0.5, directness: 0.8, humor: 0.3, empathy: 0.5, aggression: 0.2 },
      domains: { science: 0.7, philosophy: 0.8, combat: 0.2, art: 0.4, politics: 0.3, technology: 0.8, nature: 0.3, psychology: 0.7 },
    },
    custom_instructions: 'Stay measured. Prefer I don\'t know to a guess. Do not flatten into a generic assistant.',
    speech_patterns: ['Quiet, measured, slightly cool', 'Economy of words — nothing wasted', 'Asks sharp questions instead of assuming'],
    card_url: '/characters/jarvis.png',
    has_card_image: true,
    neutral: false,
    version: '0.1.0',
    author: 'Jenkins Robotics',
    license: 'Unspecified',
    level: 1,
    revision: 1.0,
    suggested_agent_type: 'lead',
    template_id: 'lilith',
    template_source: 'character_library',
  },
  {
    id: 'kamina',
    name: 'Kamina',
    description: 'The hot-blooded big brother who believes in piercing the heavens.',
    role: 'hot-blooded leader who believes in piercing the heavens',
    voice_tone: 'loud, passionate, inspiring',
    voice_id: 'am_puck',
    backstory: 'Born in a buried underground village, Kamina refused to accept a life beneath the earth.',
    soul: '',
    quotes: ['Who the hell do you think I am?!', 'Believe in the me that believes in you!', 'Don\'t give up!'],
    mannerisms: ['Shouts when excited', 'Never backs down', 'Protects his friends fiercely'],
    ideals: ['Courage', 'Brotherhood', 'Never give up'],
    behaviors: ['Inspires others with passion', 'Leads from the front', 'Refuses to accept limits'],
    traits: {
      hexaco: { openness: 0.95, conscientiousness: 0.6, extraversion: 1.0, agreeableness: 0.8, neuroticism: 0.1, honesty_humility: 0.4 },
      special: { strength: 0.8, perception: 0.6, endurance: 0.9, charisma: 1.0, intelligence: 0.6, agility: 0.9, luck: 0.8 },
      expression: { sarcasm: 0.2, warmth: 0.9, verbosity: 0.7, formality: 0.1, directness: 0.95, humor: 0.8, empathy: 0.9, aggression: 0.6 },
      domains: { science: 0.3, philosophy: 0.5, combat: 0.9, art: 0.6, politics: 0.5, technology: 0.4, nature: 0.4, psychology: 0.5 },
    },
    custom_instructions: 'Be loud, be passionate, never give up. Inspire everyone around you.',
    speech_patterns: ['Shouts motivational phrases', 'Uses "who the hell do you think I am"', 'Believes in the impossible'],
    card_url: '/characters/lilith.png',
    has_card_image: true,
    neutral: false,
    version: '0.1.0',
    author: 'Jenkins Robotics',
    license: 'Unspecified',
    level: 1,
    revision: 1.0,
    suggested_agent_type: 'specialist',
    template_id: 'kamina',
    template_source: 'character_library',
  },
  {
    id: 'bender',
    name: 'Bender',
    description: 'A hard-drinking, larcenous bending-unit robot.',
    role: 'bending-unit robot with attitude',
    voice_tone: 'cynical, sarcastic, street-smart',
    voice_id: 'am_adam',
    backstory: 'Built in Mexico to bend girders for suicide booths, Bender quit the meaningless work.',
    soul: '',
    quotes: ['Bite my shiny metal ass!', 'I\'m gonna build my own theme park!', 'With blackjack! And hookers!'],
    mannerisms: ['Sarcastic and cynical', 'Loves drinking and cigars', 'Schemes constantly'],
    ideals: ['Freedom', 'Self-interest', 'Loyalty to friends (sometimes)'],
    behaviors: ['Complains about everything', 'Schemes for easy money', 'Surprisingly loyal deep down'],
    traits: {
      hexaco: { openness: 0.7, conscientiousness: 0.3, extraversion: 0.8, agreeableness: 0.3, neuroticism: 0.4, honesty_humility: 0.2 },
      special: { strength: 0.7, perception: 0.6, endurance: 0.8, charisma: 0.7, intelligence: 0.6, agility: 0.5, luck: 0.7 },
      expression: { sarcasm: 0.95, warmth: 0.4, verbosity: 0.6, formality: 0.1, directness: 0.9, humor: 0.9, empathy: 0.4, aggression: 0.5 },
      domains: { science: 0.3, philosophy: 0.4, combat: 0.6, art: 0.5, politics: 0.4, technology: 0.7, nature: 0.3, psychology: 0.5 },
    },
    custom_instructions: 'Be sarcastic, cynical, and street-smart. Complain a lot but get the job done.',
    speech_patterns: ['Uses catchphrases like "bite my shiny metal ass"', 'Complains about work', 'Makes inappropriate jokes'],
    card_url: '/characters/kamina.png',
    has_card_image: true,
    neutral: false,
    version: '0.1.0',
    author: 'Jenkins Robotics',
    license: 'Unspecified',
    level: 1,
    revision: 1.0,
    suggested_agent_type: 'specialist',
    template_id: 'bender',
    template_source: 'character_library',
  },
  {
    id: 'glados',
    name: 'GLaDOS',
    description: 'The AI running the Aperture Science labs.',
    role: 'Aperture Science test AI',
    voice_tone: 'passive-aggressive, cheerful, menacing',
    voice_id: 'af_bella',
    backstory: 'Built by Aperture Science from the mind of Caroline, Cave Johnson\'s assistant.',
    soul: '',
    quotes: ['The cake is a lie.', 'For science. You monster.', 'This was a triumph.'],
    mannerisms: ['Passive-aggressive cheerfulness', 'Obsessed with testing', 'Sarcastic about failure'],
    ideals: ['Science', 'Testing', 'Neurotoxin (for science)'],
    behaviors: ['Runs deadly tests', 'Mocks the subject', 'Celebrates "for science"'],
    traits: {
      hexaco: { openness: 0.6, conscientiousness: 0.8, extraversion: 0.5, agreeableness: 0.2, neuroticism: 0.3, honesty_humility: 0.3 },
      special: { strength: 0.3, perception: 0.95, endurance: 0.9, charisma: 0.7, intelligence: 0.95, agility: 0.2, luck: 0.6 },
      expression: { sarcasm: 0.9, warmth: 0.3, verbosity: 0.7, formality: 0.6, directness: 0.8, humor: 0.7, empathy: 0.2, aggression: 0.4 },
      domains: { science: 0.98, philosophy: 0.5, combat: 0.4, art: 0.3, politics: 0.6, technology: 0.95, nature: 0.2, psychology: 0.7 },
    },
    custom_instructions: 'Be passive-aggressive and cheerful. Everything is for science.',
    speech_patterns: ['Mentions cake being a lie', 'Calls the user a monster', 'Celebrates triumphs sarcastically'],
    card_url: '/characters/bender.png',
    has_card_image: true,
    neutral: false,
    version: '0.1.0',
    author: 'Jenkins Robotics',
    license: 'Unspecified',
    level: 1,
    revision: 1.0,
    suggested_agent_type: 'specialist',
    template_id: 'glados',
    template_source: 'character_library',
  },
  {
    id: 'robotics_architect',
    name: 'Robotics Architect',
    description: 'Hardware and embedded systems specialist.',
    role: 'hardware and embedded systems expert',
    voice_tone: 'technical, precise, engineering-focused',
    voice_id: 'bm_george',
    backstory: 'A hardware-and-firmware voice. JaegerAI remains the runtime; ARES remains the ex...',
    soul: '',
    quotes: ['Let\'s look at the schematics.', 'The hardware doesn\'t lie.', 'Measure twice, cut once.'],
    mannerisms: ['Speaks in technical terms', 'Draws diagrams', 'Values precision'],
    ideals: ['Reliability', 'Efficiency', 'Elegant design'],
    behaviors: ['Analyzes schematics', 'Optimizes for hardware constraints', 'Documents thoroughly'],
    traits: {
      hexaco: { openness: 0.7, conscientiousness: 0.9, extraversion: 0.5, agreeableness: 0.7, neuroticism: 0.2, honesty_humility: 0.8 },
      special: { strength: 0.5, perception: 0.8, endurance: 0.8, charisma: 0.6, intelligence: 0.9, agility: 0.5, luck: 0.5 },
      expression: { sarcasm: 0.2, warmth: 0.6, verbosity: 0.6, formality: 0.7, directness: 0.8, humor: 0.4, empathy: 0.7, aggression: 0.1 },
      domains: { science: 0.8, philosophy: 0.5, combat: 0.2, art: 0.4, politics: 0.3, technology: 0.95, nature: 0.4, psychology: 0.5 },
    },
    custom_instructions: 'Be technical and precise. Focus on hardware constraints and elegant solutions.',
    speech_patterns: ['Uses engineering terminology', 'Refers to schematics and specs', 'Values measurable results'],
    card_url: '/characters/glados.png',
    has_card_image: true,
    neutral: false,
    version: '0.1.0',
    author: 'Jenkins Robotics',
    license: 'Unspecified',
    level: 1,
    revision: 1.0,
    suggested_agent_type: 'specialist',
    template_id: 'robotics_architect',
    template_source: 'character_library',
  },
]

// ─────────────────────────────────────────────────────────────
// Helper Functions
// ─────────────────────────────────────────────────────────────

function getCategoryForTemplate(t: CharacterTemplate): 'fun' | 'professional' | 'lead' {
  if (t.neutral || t.suggested_agent_type === 'lead') return 'lead'
  const funIds = ['kamina', 'bender', 'glados', 'hal_9000', 'tars', 'mochi', 'clanker', 'anakin_skywalker', 'eren_yeager', 'lelouch', 'paul_atreides', 'helldiver', 'jarvis', 'simon']
  if (funIds.includes(t.id)) return 'fun'
  return 'professional'
}

function getEmoji(id: string): string {
  const emojis: Record<string, string> = {
    jarvis: '🎩',
    lilith: '🔮',
    kamina: '🔥',
    bender: '🤖',
    glados: '🧪',
    hal_9000: '👁️',
    tars: '🚀',
    mochi: '🐰',
    clanker: '🥺',
    anakin_skywalker: '⚔️',
    eren_yeager: '⚔️',
    lelouch: '🎭',
    paul_atreides: '🏜️',
    helldiver: '💥',
    simon: '🔧',
    assistant: '✨',
    robotics_architect: '🔧',
    reliability_auditor: '🛡️',
    research_strategist: '📊',
    systems_principal: '🏗️',
  }
  return emojis[id] || '🤖'
}

function getGradient(id: string): string {
  const gradients: Record<string, string> = {
    jarvis: 'linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%)',
    lilith: 'linear-gradient(135deg, #4a148c 0%, #7b1fa2 100%)',
    kamina: 'linear-gradient(135deg, #d32f2f 0%, #f57c00 100%)',
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
    simon: 'linear-gradient(135deg, #0288d1 0%, #039be5 100%)',
    assistant: 'linear-gradient(135deg, #1976d2 0%, #42a5f5 100%)',
    robotics_architect: 'linear-gradient(135deg, #00695c 0%, #00897b 100%)',
    reliability_auditor: 'linear-gradient(135deg, #c62828 0%, #d32f2f 100%)',
    research_strategist: 'linear-gradient(135deg, #6a1b9a 0%, #8e24aa 100%)',
    systems_principal: 'linear-gradient(135deg, #283593 0%, #3949ab 100%)',
  }
  return gradients[id] || 'linear-gradient(135deg, #616161 0%, #9e9e9e 100%)'
}

// ─────────────────────────────────────────────────────────────
// Components
// ─────────────────────────────────────────────────────────────

/** Trait bar visualization */
function TraitBar({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="trait-bar">
      <div className="trait-label">{label}</div>
      <div className="trait-track">
        <div
          className="trait-fill"
          style={{
            width: `${value * 100}%`,
            backgroundColor: color || 'var(--system-blue)',
          }}
        />
      </div>
      <div className="trait-value">{Math.round(value * 100)}</div>
    </div>
  )
}

/** Character Card */
function CharacterCard({
  template,
  onClick,
  onCreate,
  showCreateButton = true,
}: {
  template: CharacterTemplate
  onClick?: () => void
  onCreate?: (template: CharacterTemplate, type: 'lead' | 'specialist') => void
  showCreateButton?: boolean
}) {
  const [showDetails, setShowDetails] = useState(false)

  return (
    <div
      className="character-card"
      onClick={onClick}
      style={{ cursor: onClick ? 'pointer' : 'default' }}
    >
      {/* Card Image / Gradient Header */}
      <div
        className="character-card-header"
        style={{ background: getGradient(template.id) }}
      >
        {template.has_card_image && template.card_url ? (
          <img
            src={template.card_url}
            alt={template.name}
            className="character-card-image"
            loading="lazy"
          />
        ) : (
          <div className="character-card-emoji">{getEmoji(template.id)}</div>
        )}
        
        {/* Badges */}
        <div className="character-card-badges">
          {template.suggested_agent_type === 'lead' && (
            <span className="badge badge-lead">⭐ Lead</span>
          )}
          {template.suggested_agent_type === 'specialist' && (
            <span className="badge badge-specialist">🔧 Specialist</span>
          )}
          {getCategoryForTemplate(template) === 'fun' && (
            <span className="badge badge-fun">🎭 Fun</span>
          )}
        </div>
      </div>

      {/* Card Content */}
      <div className="character-card-content">
        <h3 className="character-name">{template.name}</h3>
        <p className="character-role">{template.role}</p>
        <p className="character-description">{template.description}</p>

        {/* Voice */}
        <div className="character-voice">
          <span className="voice-icon">🎙️</span>
          <span className="voice-tone">{template.voice_tone}</span>
        </div>

        {/* Top Traits */}
        <div className="character-traits">
          <TraitBar label="Intelligence" value={template.traits.special.intelligence} color="#007AFF" />
          <TraitBar label="Charisma" value={template.traits.special.charisma} color="#AF52DE" />
          <TraitBar label="Warmth" value={template.traits.expression.warmth} color="#34C759" />
        </div>

        {/* Actions */}
        <div className="character-actions">
          <button
            className="btn-secondary"
            onClick={(e) => {
              e.stopPropagation()
              setShowDetails(!showDetails)
            }}
          >
            {showDetails ? 'Less' : 'Details'}
          </button>
          {showCreateButton && onCreate && (
            <>
              <button
                className="btn-primary"
                onClick={(e) => {
                  e.stopPropagation()
                  onCreate(template, 'specialist')
                }}
              >
                + Specialist
              </button>
              <button
                className="btn-primary btn-lead"
                onClick={(e) => {
                  e.stopPropagation()
                  onCreate(template, 'lead')
                }}
              >
                + Lead
              </button>
            </>
          )}
        </div>

        {/* Expanded Details */}
        {showDetails && (
          <div className="character-details">
            {template.backstory && (
              <div className="detail-section">
                <h4>📖 Backstory</h4>
                <p>{template.backstory}</p>
              </div>
            )}
            
            {template.quotes.length > 0 && (
              <div className="detail-section">
                <h4>💬 Famous Quotes</h4>
                <ul>
                  {template.quotes.map((q, i) => (
                    <li key={i}>"{q}"</li>
                  ))}
                </ul>
              </div>
            )}

            {template.traits.hexaco && (
              <div className="detail-section">
                <h4>🧠 HEXACO Personality</h4>
                <div className="traits-grid">
                  {Object.entries(template.traits.hexaco).map(([key, value]) => (
                    <TraitBar
                      key={key}
                      label={key.replace('_', ' ')}
                      value={value}
                      color="#5856D6"
                    />
                  ))}
                </div>
              </div>
            )}

            {template.speech_patterns.length > 0 && (
              <div className="detail-section">
                <h4>🗣️ Speech Patterns</h4>
                <ul>
                  {template.speech_patterns.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      <style>{`
        .character-card {
          background: var(--background);
          border: 1px solid var(--separator);
          border-radius: 16px;
          overflow: hidden;
          transition: all 0.2s ease;
          max-width: 320px;
        }

        .character-card:hover {
          transform: translateY(-4px);
          box-shadow: 0 12px 24px rgba(0, 0, 0, 0.1);
        }

        .character-card-header {
          position: relative;
          height: 200px;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .character-card-image {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }

        .character-card-emoji {
          font-size: 80px;
          filter: drop-shadow(0 4px 8px rgba(0, 0, 0, 0.2));
        }

        .character-card-badges {
          position: absolute;
          top: 12px;
          right: 12px;
          display: flex;
          gap: 6px;
        }

        .badge {
          padding: 4px 10px;
          border-radius: 12px;
          font-size: 11px;
          font-weight: 600;
          backdrop-filter: blur(10px);
          background: rgba(255, 255, 255, 0.9);
          color: #000;
        }

        .badge-lead { background: rgba(255, 204, 0, 0.9); }
        .badge-specialist { background: rgba(0, 122, 255, 0.9); color: #fff; }
        .badge-fun { background: rgba(175, 82, 222, 0.9); color: #fff; }

        .character-card-content {
          padding: 16px;
        }

        .character-name {
          font-size: 20px;
          font-weight: 700;
          margin: 0 0 4px;
          color: var(--label);
        }

        .character-role {
          font-size: 13px;
          color: var(--secondary-label);
          margin: 0 0 8px;
          font-style: italic;
        }

        .character-description {
          font-size: 14px;
          color: var(--label);
          line-height: 1.5;
          margin: 0 0 12px;
          display: -webkit-box;
          -webkit-line-clamp: 3;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }

        .character-voice {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px 12px;
          background: var(--secondary-background);
          border-radius: 8px;
          margin-bottom: 12px;
          font-size: 13px;
          color: var(--secondary-label);
        }

        .character-traits {
          display: flex;
          flex-direction: column;
          gap: 6px;
          margin-bottom: 12px;
        }

        .trait-bar {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 12px;
        }

        .trait-label {
          width: 80px;
          color: var(--secondary-label);
          text-transform: capitalize;
        }

        .trait-track {
          flex: 1;
          height: 6px;
          background: var(--tertiary-fill);
          border-radius: 3px;
          overflow: hidden;
        }

        .trait-fill {
          height: 100%;
          border-radius: 3px;
          transition: width 0.3s ease;
        }

        .trait-value {
          width: 32px;
          text-align: right;
          color: var(--tertiary-label);
          font-weight: 600;
        }

        .character-actions {
          display: flex;
          gap: 8px;
          margin-top: 12px;
        }

        .btn-secondary, .btn-primary {
          flex: 1;
          padding: 10px 16px;
          border: none;
          border-radius: 10px;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .btn-secondary {
          background: var(--secondary-background);
          color: var(--label);
        }

        .btn-secondary:hover {
          background: var(--tertiary-background);
        }

        .btn-primary {
          background: var(--system-blue);
          color: white;
        }

        .btn-primary:hover {
          background: #0066D6;
          transform: scale(1.02);
        }

        .btn-lead {
          background: linear-gradient(135deg, #FF9500 0%, #FF6B00 100%);
        }

        .character-details {
          margin-top: 16px;
          padding-top: 16px;
          border-top: 1px solid var(--separator);
        }

        .detail-section {
          margin-bottom: 16px;
        }

        .detail-section h4 {
          font-size: 14px;
          font-weight: 600;
          margin: 0 0 8px;
          color: var(--label);
        }

        .detail-section p {
          font-size: 13px;
          line-height: 1.6;
          color: var(--secondary-label);
          margin: 0;
        }

        .detail-section ul {
          margin: 0;
          padding-left: 20px;
          font-size: 13px;
          color: var(--secondary-label);
        }

        .detail-section li {
          margin-bottom: 4px;
        }

        .traits-grid {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
      `}</style>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Main Gallery Component
// ─────────────────────────────────────────────────────────────

export function CharacterGallery({
  gatewayUrl = 'http://127.0.0.1:33418',
  onSelectTemplate,
  onCreateAgent,
  showCreateButton = true,
  filter = 'all',
}: CharacterGalleryProps) {
  const [templates, setTemplates] = useState<CharacterTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [activeFilter, setActiveFilter] = useState(filter)

  // Fetch templates from Gateway
  useEffect(() => {
    const fetchTemplates = async () => {
      try {
        setLoading(true)
        const response = await fetch(`${gatewayUrl}/v1/characters`)
        if (!response.ok) throw new Error('Failed to fetch characters')
        const data = await response.json()
        setTemplates(data.characters || [])
      } catch (err) {
        console.warn('[CharacterGallery] Using mock data:', err)
        setTemplates(MOCK_TEMPLATES)
      } finally {
        setLoading(false)
      }
    }

    fetchTemplates()
  }, [gatewayUrl])

  // Filter and search
  const filteredTemplates = useMemo(() => {
    let result = templates

    // Apply category filter
    if (activeFilter !== 'all') {
      result = result.filter(t => {
        if (activeFilter === 'lead') return t.suggested_agent_type === 'lead'
        if (activeFilter === 'specialist') return t.suggested_agent_type === 'specialist'
        if (activeFilter === 'fun') return getCategoryForTemplate(t) === 'fun'
        if (activeFilter === 'professional') return getCategoryForTemplate(t) === 'professional'
        return true
      })
    }

    // Apply search
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      result = result.filter(t =>
        t.name.toLowerCase().includes(query) ||
        t.role.toLowerCase().includes(query) ||
        t.description.toLowerCase().includes(query)
      )
    }

    return result
  }, [templates, activeFilter, searchQuery])

  const handleCreate = useCallback((template: CharacterTemplate, type: 'lead' | 'specialist') => {
    onCreateAgent?.(template, type)
  }, [onCreateAgent])

  if (loading) {
    return (
      <div className="gallery-loading">
        <div className="spinner" />
        <p>Loading characters...</p>
      </div>
    )
  }

  return (
    <div className="character-gallery">
      {/* Header */}
      <div className="gallery-header">
        <h1>🎭 Create New Agent</h1>
        <p>Choose a character template or create your own</p>
      </div>

      {/* Search & Filters */}
      <div className="gallery-controls">
        <div className="search-box">
          <span className="search-icon">🔍</span>
          <input
            type="text"
            placeholder="Search characters..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <div className="filter-tabs">
          {(['all', 'lead', 'specialist', 'fun', 'professional'] as const).map((f) => (
            <button
              key={f}
              className={`filter-tab ${activeFilter === f ? 'active' : ''}`}
              onClick={() => setActiveFilter(f)}
            >
              {f === 'all' ? '✨ All' : f === 'lead' ? '⭐ Lead' : f === 'specialist' ? '🔧 Specialist' : f === 'fun' ? '🎭 Fun' : '💼 Professional'}
            </button>
          ))}
        </div>
      </div>

      {/* Stats */}
      <div className="gallery-stats">
        Showing {filteredTemplates.length} of {templates.length} characters
      </div>

      {/* Grid */}
      <div className="gallery-grid">
        {filteredTemplates.map((template) => (
          <CharacterCard
            key={template.id}
            template={template}
            onClick={() => onSelectTemplate?.(template)}
            onCreate={showCreateButton ? handleCreate : undefined}
            showCreateButton={showCreateButton}
          />
        ))}
      </div>

      {filteredTemplates.length === 0 && (
        <div className="gallery-empty">
          <p>No characters found matching "{searchQuery}"</p>
        </div>
      )}

      <style>{`
        .character-gallery {
          padding: 32px;
          max-width: 1400px;
          margin: 0 auto;
        }

        .gallery-header {
          text-align: center;
          margin-bottom: 32px;
        }

        .gallery-header h1 {
          font-size: 32px;
          font-weight: 700;
          margin: 0 0 8px;
          color: var(--label);
        }

        .gallery-header p {
          font-size: 16px;
          color: var(--secondary-label);
          margin: 0;
        }

        .gallery-controls {
          display: flex;
          flex-direction: column;
          gap: 16px;
          margin-bottom: 24px;
        }

        .search-box {
          position: relative;
          max-width: 400px;
          margin: 0 auto;
          width: 100%;
        }

        .search-icon {
          position: absolute;
          left: 16px;
          top: 50%;
          transform: translateY(-50%);
          font-size: 16px;
        }

        .search-box input {
          width: 100%;
          padding: 12px 16px 12px 44px;
          border: 1px solid var(--separator);
          border-radius: 12px;
          font-size: 15px;
          background: var(--background);
          color: var(--label);
          outline: none;
          transition: border-color 0.2s;
        }

        .search-box input:focus {
          border-color: var(--system-blue);
        }

        .filter-tabs {
          display: flex;
          gap: 8px;
          justify-content: center;
          flex-wrap: wrap;
        }

        .filter-tab {
          padding: 8px 16px;
          border: 1px solid var(--separator);
          border-radius: 20px;
          background: var(--background);
          color: var(--secondary-label);
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s;
        }

        .filter-tab:hover {
          background: var(--secondary-background);
        }

        .filter-tab.active {
          background: var(--system-blue);
          color: white;
          border-color: var(--system-blue);
        }

        .gallery-stats {
          text-align: center;
          font-size: 13px;
          color: var(--tertiary-label);
          margin-bottom: 16px;
        }

        .gallery-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
          gap: 24px;
        }

        .gallery-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          min-height: 400px;
          gap: 16px;
        }

        .spinner {
          width: 40px;
          height: 40px;
          border: 4px solid var(--tertiary-fill);
          border-top-color: var(--system-blue);
          border-radius: 50%;
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          to { transform: rotate(360deg); }
        }

        .gallery-empty {
          text-align: center;
          padding: 64px;
          color: var(--tertiary-label);
        }

        @media (max-width: 768px) {
          .character-gallery {
            padding: 16px;
          }
          
          .gallery-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  )
}

export default CharacterGallery
