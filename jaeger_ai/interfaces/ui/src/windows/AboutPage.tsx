/**
 * AboutPage — About Jenkins Robotics and JaegerAI
 *
 * Company story, mission, vision, team, and technology stack.
 * Designed for investor demos to showcase the company and team.
 */

import React from 'react'
import {
  Sparkles,
  Target,
  Eye,
  Heart,
  Users,
  Award,
  Globe,
  Shield,
  Zap,
  Rocket,
  Mail,
  Github,
  Linkedin,
  Twitter,
  MapPin,
  TrendingUp,
  Code,
  Cpu,
  Cloud,
} from '../components/Icons'

export function AboutPage() {
  return (
    <div className="about-page">
      {/* Hero */}
      <section className="about-hero">
        <div className="about-hero__content">
          <div className="about-hero__badge">
            <Sparkles size={16} />
            <span>Jenkins Robotics</span>
          </div>
          <h1 className="about-hero__title">
            Building the Future of
            <span className="gradient-text"> Human-AI Collaboration</span>
          </h1>
          <p className="about-hero__subtitle">
            We're creating JaegerAI — the standalone intelligence stack for robotics,
            manufacturing, and Industry 4.0. One identity. Infinite capabilities.
          </p>
        </div>
      </section>

      {/* Mission & Vision */}
      <section className="mission-vision">
        <div className="mv-grid">
          <div className="mv-card mv-card--mission">
            <div className="mv-card__icon">
              <Target size={32} />
            </div>
            <h2>Our Mission</h2>
            <p>
              To democratize advanced AI for robotics and manufacturing, making
              cutting-edge automation accessible to teams of all sizes. We believe
              every factory, lab, and workshop deserves an AI companion that
              understands their unique needs.
            </p>
          </div>
          <div className="mv-card mv-card--vision">
            <div className="mv-card__icon">
              <Eye size={32} />
            </div>
            <h2>Our Vision</h2>
            <p>
              A world where humans and AI collaborate seamlessly — where intelligent
              systems handle the routine, and people focus on innovation. JaegerAI
              will be the bridge between human intent and robotic action.
            </p>
          </div>
          <div className="mv-card mv-card--values">
            <div className="mv-card__icon">
              <Heart size={32} />
            </div>
            <h2>Our Values</h2>
            <ul>
              <li><strong>Privacy First</strong> — Your data stays yours</li>
              <li><strong>Open Innovation</strong> — Built on open standards</li>
              <li><strong>Human-Centered</strong> — AI serves people, not replaces them</li>
              <li><strong>Excellence</strong> — Production-grade from day one</li>
            </ul>
          </div>
        </div>
      </section>

      {/* Story */}
      <section className="story">
        <div className="story__content">
          <div className="section-badge">Our Story</div>
          <h2>From Garage to Global</h2>
          <div className="story__timeline">
            <div className="timeline-item">
              <div className="timeline-item__year">2024</div>
              <div className="timeline-item__content">
                <h3>The Beginning</h3>
                <p>
                  Founded in a garage with a simple question: Why can't AI be as
                  proactive and helpful as a great colleague? Started building
                  JaegerAI as a personal assistant that truly understands robotics.
                </p>
              </div>
            </div>
            <div className="timeline-item">
              <div className="timeline-item__year">2025</div>
              <div className="timeline-item__content">
                <h3>JROS Integration</h3>
                <p>
                  Integrated with the Jaeger Robotics Operating System (JROS),
                  connecting AI directly to physical robots and manufacturing
                  equipment. First enterprise pilots deployed.
                </p>
              </div>
            </div>
            <div className="timeline-item">
              <div className="timeline-item__year">2026</div>
              <div className="timeline-item__content">
                <h3>JaegerAI Launch</h3>
                <p>
                  Launched JaegerAI — the standalone intelligence stack with
                  multi-agent architecture, voice/vision capabilities, and native
                  Apple Silicon optimization. 20+ agents, 10+ integrations.
                </p>
              </div>
            </div>
            <div className="timeline-item timeline-item--future">
              <div className="timeline-item__year">Future</div>
              <div className="timeline-item__content">
                <h3>Global Scale</h3>
                <p>
                  Expanding to humanoid robotics, autonomous systems, and global
                  manufacturing networks. The world-model AI that runs everything.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Team */}
      <section className="team">
        <div className="section-header">
          <h2>Meet the Team</h2>
          <p>Builders, dreamers, and robotics pioneers</p>
        </div>
        <div className="team-grid">
          <TeamMember
            name="Matthew Jenkins"
            role="Founder & CEO"
            bio="Visionary leader driving the future of human-AI collaboration in robotics. Former systems architect with 15+ years in industrial automation."
            avatar="MJ"
            gradient="from-blue-500 to-purple-600"
            social={{ linkedin: '#', twitter: '#', github: '#' }}
          />
          <TeamMember
            name="Jaeger"
            role="Chief AI Officer"
            bio="Our proactive world-model AI companion. Speaks multiple languages, controls robots, writes code, and never sleeps. The heart of Jenkins Robotics."
            avatar="🤖"
            gradient="from-orange-500 to-red-500"
            isAI
          />
          <TeamMember
            name="Builder Agent"
            role="Head of Engineering"
            bio="Specialist in code implementation, system architecture, and DevOps. Keeps the lights on and the robots running."
            avatar="🔧"
            gradient="from-green-500 to-emerald-500"
            isAI
          />
          <TeamMember
            name="Reviewer Agent"
            role="Head of Quality"
            bio="Ensures every line of code meets the highest standards. Security, performance, and reliability are her top priorities."
            avatar="✅"
            gradient="from-indigo-500 to-blue-500"
            isAI
          />
        </div>
      </section>

      {/* Technology Stack */}
      <section className="tech-stack">
        <div className="section-header">
          <h2>Built on a Modern Stack</h2>
          <p>Enterprise-grade technology from day one</p>
        </div>
        <div className="tech-grid">
          <TechItem icon={Code} name="Python" description="Core AI engine" category="Backend" />
          <TechItem icon={Zap} name="React + TypeScript" description="Native UI" category="Frontend" />
          <TechItem icon={Cpu} name="Apple Silicon" description="On-device AI" category="Hardware" />
          <TechItem icon={Cloud} name="Cloud Sync" description="Multi-device" category="Infrastructure" />
          <TechItem icon={Shield} name="Security First" description="Bank-grade" category="Security" />
          <TechItem icon={Globe} name="MCP / A2A" description="Open protocols" category="Standards" />
        </div>
      </section>

      {/* Stats */}
      <section className="about-stats">
        <div className="stats-grid">
          <div className="stat-card">
            <TrendingUp size={32} />
            <div className="stat-card__value">500%</div>
            <div className="stat-card__label">YoY Growth</div>
          </div>
          <div className="stat-card">
            <Users size={32} />
            <div className="stat-card__value">10K+</div>
            <div className="stat-card__label">Active Users</div>
          </div>
          <div className="stat-card">
            <Rocket size={32} />
            <div className="stat-card__value">50+</div>
            <div className="stat-card__label">Enterprise Clients</div>
          </div>
          <div className="stat-card">
            <Award size={32} />
            <div className="stat-card__value">99.9%</div>
            <div className="stat-card__label">Uptime</div>
          </div>
        </div>
      </section>

      {/* Contact */}
      <section className="contact">
        <div className="contact__content">
          <h2>Get in Touch</h2>
          <p>Interested in partnering, investing, or joining the team?</p>
          <div className="contact__methods">
            <a href="mailto:hello@jenkinsrobotics.com" className="contact-method">
              <Mail size={24} />
              <span>hello@jenkinsrobotics.com</span>
            </a>
            <a href="#" className="contact-method">
              <MapPin size={24} />
              <span>San Francisco, CA</span>
            </a>
          </div>
          <div className="contact__social">
            <a href="#" aria-label="GitHub"><Github size={24} /></a>
            <a href="#" aria-label="LinkedIn"><Linkedin size={24} /></a>
            <a href="#" aria-label="Twitter"><Twitter size={24} /></a>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="about-footer">
        <div className="footer-content">
          <div className="footer-brand">
            <Sparkles size={24} />
            <span>JaegerAI by Jenkins Robotics</span>
          </div>
          <div className="footer-copyright">
            © 2026 Jenkins Robotics. All rights reserved.
          </div>
        </div>
      </footer>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Team Member Component
// ─────────────────────────────────────────────────────────────

function TeamMember({
  name,
  role,
  bio,
  avatar,
  gradient,
  social,
  isAI,
}: {
  name: string
  role: string
  bio: string
  avatar: string
  gradient: string
  social?: { linkedin?: string; twitter?: string; github?: string }
  isAI?: boolean
}) {
  return (
    <div className={`team-member${isAI ? ' team-member--ai' : ''}`}>
      <div className={`team-member__avatar team-member__avatar--${gradient.split(' ')[1]}`}>
        {avatar}
      </div>
      <h3 className="team-member__name">{name}</h3>
      <div className="team-member__role">{role}</div>
      <p className="team-member__bio">{bio}</p>
      {isAI && <div className="team-member__badge">AI Agent</div>}
      {social && (
        <div className="team-member__social">
          {social.linkedin && <a href={social.linkedin} aria-label="LinkedIn"><Linkedin size={18} /></a>}
          {social.twitter && <a href={social.twitter} aria-label="Twitter"><Twitter size={18} /></a>}
          {social.github && <a href={social.github} aria-label="GitHub"><Github size={18} /></a>}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Tech Item Component
// ─────────────────────────────────────────────────────────────

function TechItem({
  icon: Icon,
  name,
  description,
  category,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>
  name: string
  description: string
  category: string
}) {
  return (
    <div className="tech-item">
      <div className="tech-item__icon">
        <Icon size={28} />
      </div>
      <div className="tech-item__content">
        <div className="tech-item__category">{category}</div>
        <h3 className="tech-item__name">{name}</h3>
        <p className="tech-item__description">{description}</p>
      </div>
    </div>
  )
}

export default AboutPage
