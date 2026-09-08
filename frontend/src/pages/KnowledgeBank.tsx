import { useEffect, useState } from 'react'
import { get } from '../lib/api'
import { PageHeader, Skeleton } from '../components/ui'
import { EvidenceList } from '../components/Evidence'
import type { EvidenceRef } from '../lib/types'

interface Card {
  id: string
  category: string
  title: string
  body: string
  limitations: string[]
  references: EvidenceRef[]
}

export function KnowledgeBank() {
  const [data, setData] = useState<{ cards: Card[]; glossary: { term: string; definition: string }[] } | null>(null)

  useEffect(() => {
    void get<typeof data>('/api/program/knowledge-bank').then(setData)
  }, [])

  if (!data) {
    return (
      <>
        <PageHeader title="Knowledge Bank" />
        <Skeleton lines={4} />
        <span className="visually-hidden" role="status">
          Loading
        </span>
      </>
    )
  }

  const categories = Array.from(new Set(data.cards.map((c) => c.category)))

  return (
    <>
      <h2>Knowledge Bank</h2>
      <p className="lede">
        Concepts, how each kind of data is generated, and what each method can and cannot
        tell you.
      </p>

      {categories.map((category) => (
        <section key={category}>
          <h3>{category}</h3>
          <div className="grid">
            {data.cards
              .filter((card) => card.category === category)
              .map((card) => (
                <article className="card" key={card.id}>
                  <h3>{card.title}</h3>
                  <p>{card.body}</p>
                  {card.limitations.map((limitation) => (
                    <p className="caveat" key={limitation}>
                      {limitation}
                    </p>
                  ))}
                  <EvidenceList sources={card.references} />
                </article>
              ))}
          </div>
        </section>
      ))}

      <section>
        <h3>Glossary</h3>
        <div className="card scroll">
          <table>
            <tbody>
              {data.glossary.map((entry) => (
                <tr key={entry.term}>
                  <th style={{ width: 220 }}>{entry.term}</th>
                  <td>{entry.definition}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}
