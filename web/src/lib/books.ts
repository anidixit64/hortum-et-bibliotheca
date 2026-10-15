import type { Book } from '../api/types'

/** An even shelf, eight when there are that many, otherwise the next even count down. */
export function evenShelf(books: Book[], aim = 8): Book[] {
  const take = books.filter((book) => book.title).slice(0, aim)
  if (take.length <= 1) return take
  return take.slice(0, take.length - (take.length % 2))
}

export function bookCover(book: Book): string | null {
  if (book.cover) return book.cover
  const isbn = (book.isbn ?? '').replace(/[^0-9Xx]/g, '')
  if (isbn.length === 10 || isbn.length === 13) {
    return `https://covers.openlibrary.org/b/isbn/${isbn}-L.jpg`
  }
  return null
}
