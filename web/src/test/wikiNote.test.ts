import { wikiNote } from '../lib/wikiNote'

const wiki = {
  title: 'RMS Titanic',
  url: 'https://en.wikipedia.org/wiki/Titanic',
  lead: 'RMS Titanic was a British ocean liner that sank in the North Atlantic Ocean in 1912.',
  sections: [
    {
      heading: 'Sinking',
      text: 'The ship struck an iceberg and the crew sent a wireless distress call. Lifeboats left half empty.',
    },
  ],
  license: 'CC BY-SA 4.0',
  license_url: 'https://creativecommons.org/licenses/by-sa/4.0/',
  attribution: 'Wikipedia',
}

test('a clue note comes from the matching Wikipedia section', () => {
  const note = wikiNote('iceberg', [], wiki)
  expect(note?.heading).toBe('Sinking')
  expect(note?.sentence).toMatch(/iceberg/)
})

test('a clue the article never mentions is left unmatched', () => {
  expect(wikiNote('Californian', ['SS Californian'], wiki)).toBeNull()
})
