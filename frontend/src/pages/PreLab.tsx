import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get, post } from '../lib/api'

interface Question {
  id: string
  prompt: string
  options: string[]
  reviewTopic: string
}

interface Result {
  score: number
  correct: number
  total: number
  feedback: { id: string; correct: boolean; explanation: string; reviewTopic: string }[]
  recommendedTopics: string[]
}

export function PreLab() {
  const [questions, setQuestions] = useState<Question[]>([])
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [result, setResult] = useState<Result | null>(null)

  useEffect(() => {
    void get<{ questions: Question[] }>('/api/program/pre-lab').then((d) => setQuestions(d.questions))
  }, [])

  async function submit() {
    setResult(await post<Result>('/api/program/pre-lab', { responses: answers }))
  }

  return (
    <>
      <h2>Pre-Lab Assessment</h2>
      <p className="lede">
        A short check of the concepts the week depends on. Wrong answers point you at the
        Knowledge Bank rather than blocking you.
      </p>

      {questions.map((question) => {
        const feedback = result?.feedback.find((f) => f.id === question.id)
        return (
          <div className="card" key={question.id}>
            <h3>{question.prompt}</h3>
            {question.options.map((option, index) => (
              <label key={option} style={{ fontWeight: 400, display: 'flex', gap: 8 }}>
                <input
                  type="radio"
                  name={question.id}
                  style={{ width: 'auto' }}
                  disabled={Boolean(result)}
                  checked={answers[question.id] === index}
                  onChange={() => setAnswers({ ...answers, [question.id]: index })}
                />
                {option}
              </label>
            ))}
            {feedback ? (
              <p className={feedback.correct ? 'hint' : 'warning'}>{feedback.explanation}</p>
            ) : null}
          </div>
        )
      })}

      {result ? (
        <div className="card">
          <h3>
            {result.correct} of {result.total} correct
          </h3>
          {result.recommendedTopics.length ? (
            <>
              <p>Review these before starting the analysis:</p>
              <ul>
                {result.recommendedTopics.map((topic) => (
                  <li key={topic}>
                    <Link to="/knowledge-bank">{topic.replace(/-/g, ' ')}</Link>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p>Nothing flagged for review.</p>
          )}
        </div>
      ) : (
        <button disabled={Object.keys(answers).length !== questions.length} onClick={submit}>
          Submit answers
        </button>
      )}
    </>
  )
}
