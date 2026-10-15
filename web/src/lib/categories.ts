export interface CategoryCard {
  slug: string
  label: string
  image: string
  category: string
  subcategory?: string
  altSubcategory?: string
}

export interface CategorySection {
  title: string
  cards: CategoryCard[]
}

const IMG = 'https://upload.wikimedia.org/wikipedia/commons/thumb'

export const SECTIONS: CategorySection[] = [
  {
    title: 'Literature',
    cards: [
      { slug: 'american-literature', label: 'American Literature', image: `${IMG}/7/7a/Mark_Twain_by_AF_Bradley_%28cropped_2%29.jpg/330px-Mark_Twain_by_AF_Bradley_%28cropped_2%29.jpg`, category: 'Literature', subcategory: 'American Literature' },
      { slug: 'british-literature', label: 'British Literature', image: `${IMG}/2/21/William_Shakespeare_by_John_Taylor%2C_edited.jpg/330px-William_Shakespeare_by_John_Taylor%2C_edited.jpg`, category: 'Literature', subcategory: 'British Literature' },
      { slug: 'classical-literature', label: 'Classical Literature', image: `${IMG}/f/f1/Homer_At_the_British_Museum_2024_%283x4_cropped%29.jpg/330px-Homer_At_the_British_Museum_2024_%283x4_cropped%29.jpg`, category: 'Literature', subcategory: 'Classical Literature' },
      { slug: 'european-literature', label: 'European Literature', image: `${IMG}/2/26/Franz_Kafka%2C_1923.jpg/330px-Franz_Kafka%2C_1923.jpg`, category: 'Literature', subcategory: 'European Literature' },
      { slug: 'world-literature', label: 'World Literature', image: `${IMG}/0/0d/Garcia_Marquez.jpg/330px-Garcia_Marquez.jpg`, category: 'Literature', subcategory: 'World Literature' },
      { slug: 'other-literature', label: 'Other Literature', image: `${IMG}/a/a8/LOC_Main_Reading_Room_Highsmith.jpg/330px-LOC_Main_Reading_Room_Highsmith.jpg`, category: 'Literature', subcategory: 'Other Literature' },
      { slug: 'drama', label: 'Drama', image: `${IMG}/8/8e/Wenceslaus-Hollar-The-second-Globe-Theatre.jpg/330px-Wenceslaus-Hollar-The-second-Globe-Theatre.jpg`, category: 'Literature', altSubcategory: 'Drama' },
      { slug: 'long-fiction', label: 'Long Fiction', image: `${IMG}/b/ba/Title_page_first_edition_Don_Quijote.jpg/330px-Title_page_first_edition_Don_Quijote.jpg`, category: 'Literature', altSubcategory: 'Long Fiction' },
      { slug: 'poetry', label: 'Poetry', image: `${IMG}/5/56/Black-white_photograph_of_Emily_Dickinson2.png/330px-Black-white_photograph_of_Emily_Dickinson2.png`, category: 'Literature', altSubcategory: 'Poetry' },
      { slug: 'short-fiction', label: 'Short Fiction', image: `${IMG}/9/93/Anton_Chekhov_1889.jpg/330px-Anton_Chekhov_1889.jpg`, category: 'Literature', altSubcategory: 'Short Fiction' },
      { slug: 'misc-literature', label: 'Misc Literature', image: `${IMG}/b/b6/Gutenberg_Bible%2C_Lenox_Copy%2C_New_York_Public_Library%2C_2009._Pic_01.jpg/330px-Gutenberg_Bible%2C_Lenox_Copy%2C_New_York_Public_Library%2C_2009._Pic_01.jpg`, category: 'Literature', altSubcategory: 'Misc Literature' },
    ],
  },
  {
    title: 'History',
    cards: [
      { slug: 'american-history', label: 'American History', image: `${IMG}/8/87/Mount_Rushmore_detail_view_%28100MP%29.jpg/330px-Mount_Rushmore_detail_view_%28100MP%29.jpg`, category: 'History', subcategory: 'American History' },
      { slug: 'ancient-history', label: 'Ancient History', image: `${IMG}/d/da/The_Parthenon_in_Athens.jpg/330px-The_Parthenon_in_Athens.jpg`, category: 'History', subcategory: 'Ancient History' },
      { slug: 'european-history', label: 'European History', image: `${IMG}/4/4e/Prise_de_la_Bastille.jpg/330px-Prise_de_la_Bastille.jpg`, category: 'History', subcategory: 'European History' },
      { slug: 'world-history', label: 'World History', image: `${IMG}/1/12/Caravane_sur_la_route_de_la_soie_-_Atlas_catalan.jpg/330px-Caravane_sur_la_route_de_la_soie_-_Atlas_catalan.jpg`, category: 'History', subcategory: 'World History' },
      { slug: 'other-history', label: 'Other History', image: `${IMG}/2/23/Rosetta_Stone.JPG/330px-Rosetta_Stone.JPG`, category: 'History', subcategory: 'Other History' },
    ],
  },
  {
    title: 'Science',
    cards: [
      { slug: 'biology', label: 'Biology', image: `${IMG}/3/37/Wilson1900Fig2.jpg/330px-Wilson1900Fig2.jpg`, category: 'Science', subcategory: 'Biology' },
      { slug: 'chemistry', label: 'Chemistry', image: `${IMG}/0/03/Simple_Periodic_Table_Chart-blocks.svg/330px-Simple_Periodic_Table_Chart-blocks.svg.png`, category: 'Science', subcategory: 'Chemistry' },
      { slug: 'physics', label: 'Physics', image: `${IMG}/3/3e/Einstein_1921_by_F_Schmutzer_-_restoration.jpg/330px-Einstein_1921_by_F_Schmutzer_-_restoration.jpg`, category: 'Science', subcategory: 'Physics' },
      { slug: 'other-science', label: 'Other Science', image: `${IMG}/b/b9/International_Space_Station.jpg/330px-International_Space_Station.jpg`, category: 'Science', subcategory: 'Other Science' },
      { slug: 'math', label: 'Math', image: `${IMG}/d/d2/Pythagorean.svg/330px-Pythagorean.svg.png`, category: 'Science', altSubcategory: 'Math' },
      { slug: 'astronomy', label: 'Astronomy', image: `${IMG}/6/68/Pillars_of_creation_2014_HST_WFC3-UVIS_full-res_denoised.jpg/330px-Pillars_of_creation_2014_HST_WFC3-UVIS_full-res_denoised.jpg`, category: 'Science', altSubcategory: 'Astronomy' },
      { slug: 'computer-science', label: 'Computer Science', image: `${IMG}/a/a1/Alan_Turing_Aged_16.jpg/330px-Alan_Turing_Aged_16.jpg`, category: 'Science', altSubcategory: 'Computer Science' },
      { slug: 'earth-science', label: 'Earth Science', image: `${IMG}/9/9e/USA_10654_Grand_Canyon_Luca_Galuzzi_2007.jpg/330px-USA_10654_Grand_Canyon_Luca_Galuzzi_2007.jpg`, category: 'Science', altSubcategory: 'Earth Science' },
      { slug: 'engineering', label: 'Engineering', image: `${IMG}/0/0c/GoldenGateBridge-001.jpg/330px-GoldenGateBridge-001.jpg`, category: 'Science', altSubcategory: 'Engineering' },
      { slug: 'misc-science', label: 'Misc Science', image: `${IMG}/d/d4/N.Tesla.JPG/330px-N.Tesla.JPG`, category: 'Science', altSubcategory: 'Misc Science' },
    ],
  },
  {
    title: 'Fine Arts',
    cards: [
      { slug: 'visual-fine-arts', label: 'Visual Fine Arts', image: `${IMG}/e/ea/Van_Gogh_-_Starry_Night_-_Google_Art_Project.jpg/330px-Van_Gogh_-_Starry_Night_-_Google_Art_Project.jpg`, category: 'Fine Arts', subcategory: 'Visual Fine Arts' },
      { slug: 'auditory-fine-arts', label: 'Auditory Fine Arts', image: `${IMG}/6/6f/Beethoven.jpg/330px-Beethoven.jpg`, category: 'Fine Arts', subcategory: 'Auditory Fine Arts' },
      { slug: 'other-fine-arts', label: 'Other Fine Arts', image: `${IMG}/7/7c/Sydney_Opera_House_-_Dec_2008.jpg/330px-Sydney_Opera_House_-_Dec_2008.jpg`, category: 'Fine Arts', subcategory: 'Other Fine Arts' },
      { slug: 'architecture', label: 'Architecture', image: `${IMG}/1/1d/Taj_Mahal_%28Edited%29.jpeg/330px-Taj_Mahal_%28Edited%29.jpeg`, category: 'Fine Arts', altSubcategory: 'Architecture' },
      { slug: 'dance', label: 'Dance', image: `${IMG}/b/bd/Anna_Pavlova_dancing.jpg/330px-Anna_Pavlova_dancing.jpg`, category: 'Fine Arts', altSubcategory: 'Dance' },
      { slug: 'film', label: 'Film', image: `${IMG}/0/00/Charlie_Chaplin.jpg/330px-Charlie_Chaplin.jpg`, category: 'Fine Arts', altSubcategory: 'Film' },
      { slug: 'jazz', label: 'Jazz', image: `${IMG}/0/0e/Louis_Armstrong_restored.jpg/330px-Louis_Armstrong_restored.jpg`, category: 'Fine Arts', altSubcategory: 'Jazz' },
      { slug: 'musicals', label: 'Musicals', image: `${IMG}/a/ac/Musical_notes.svg/330px-Musical_notes.svg.png`, category: 'Fine Arts', altSubcategory: 'Musicals' },
      { slug: 'opera', label: 'Opera', image: `${IMG}/d/d4/Prudent-Louis_Leray_-_Poster_for_the_premi%C3%A8re_of_Georges_Bizet%27s_Carmen.jpg/330px-Prudent-Louis_Leray_-_Poster_for_the_premi%C3%A8re_of_Georges_Bizet%27s_Carmen.jpg`, category: 'Fine Arts', altSubcategory: 'Opera' },
      { slug: 'photography', label: 'Photography', image: `${IMG}/0/05/Ansel_Adams_and_camera.jpg/330px-Ansel_Adams_and_camera.jpg`, category: 'Fine Arts', altSubcategory: 'Photography' },
      { slug: 'misc-arts', label: 'Misc Arts', image: `${IMG}/3/30/Metropolitan_Museum_of_Art_%28The_Met%29_-_Central_Park%2C_NYC.jpg/330px-Metropolitan_Museum_of_Art_%28The_Met%29_-_Central_Park%2C_NYC.jpg`, category: 'Fine Arts', altSubcategory: 'Misc Arts' },
    ],
  },
  {
    title: 'RMPSS',
    cards: [
      { slug: 'religion', label: 'Religion', image: `${IMG}/2/2e/Sistine_Chapel_ceiling_photo_2.jpg/330px-Sistine_Chapel_ceiling_photo_2.jpg`, category: 'Religion' },
      { slug: 'mythology', label: 'Mythology', image: `${IMG}/7/7d/Poseidon_sculpture_Copenhagen_2005.jpg/330px-Poseidon_sculpture_Copenhagen_2005.jpg`, category: 'Mythology' },
      { slug: 'philosophy', label: 'Philosophy', image: `${IMG}/5/56/The_Thinker%2C_Rodin.jpg/330px-The_Thinker%2C_Rodin.jpg`, category: 'Philosophy' },
      { slug: 'social-science', label: 'Social Science', image: `${IMG}/3/36/Sigmund_Freud%2C_by_Max_Halberstadt_%28cropped%29.jpg/330px-Sigmund_Freud%2C_by_Max_Halberstadt_%28cropped%29.jpg`, category: 'Social Science' },
      { slug: 'anthropology', label: 'Anthropology', image: `${IMG}/9/99/Margaret_Mead_%281901-1978%29.jpg/330px-Margaret_Mead_%281901-1978%29.jpg`, category: 'Social Science', altSubcategory: 'Anthropology' },
      { slug: 'economics', label: 'Economics', image: `${IMG}/4/43/Adam_Smith_The_Muir_portrait.jpg/330px-Adam_Smith_The_Muir_portrait.jpg`, category: 'Social Science', altSubcategory: 'Economics' },
      { slug: 'linguistics', label: 'Linguistics', image: `${IMG}/2/23/Rosetta_Stone.JPG/330px-Rosetta_Stone.JPG`, category: 'Social Science', altSubcategory: 'Linguistics' },
      { slug: 'psychology', label: 'Psychology', image: `${IMG}/1/14/Chimp_Brain_in_a_jar.jpg/330px-Chimp_Brain_in_a_jar.jpg`, category: 'Social Science', altSubcategory: 'Psychology' },
      { slug: 'sociology', label: 'Sociology', image: `${IMG}/1/16/Max_Weber_1894.jpg/330px-Max_Weber_1894.jpg`, category: 'Social Science', altSubcategory: 'Sociology' },
      { slug: 'other-social-science', label: 'Other Social Science', image: `${IMG}/e/ea/United_Nations_Headquarters_in_New_York_City%2C_view_from_Roosevelt_Island.jpg/330px-United_Nations_Headquarters_in_New_York_City%2C_view_from_Roosevelt_Island.jpg`, category: 'Social Science', altSubcategory: 'Other Social Science' },
    ],
  },
  {
    title: 'Other',
    cards: [
      { slug: 'movies', label: 'Movies', image: `${IMG}/5/5a/Hollywood_Sign_%28Zuschnitt%29.jpg/330px-Hollywood_Sign_%28Zuschnitt%29.jpg`, category: 'Pop Culture', subcategory: 'Movies' },
      { slug: 'music', label: 'Music', image: `${IMG}/d/d8/The_Beatles_members_at_New_York_City_in_1964.jpg/330px-The_Beatles_members_at_New_York_City_in_1964.jpg`, category: 'Pop Culture', subcategory: 'Music' },
      { slug: 'sports', label: 'Sports', image: `${IMG}/5/5c/Olympic_rings_without_rims.svg/330px-Olympic_rings_without_rims.svg.png`, category: 'Pop Culture', subcategory: 'Sports' },
      { slug: 'television', label: 'Television', image: `${IMG}/a/a3/Television_set_from_the_early_1950s.jpg/330px-Television_set_from_the_early_1950s.jpg`, category: 'Pop Culture', subcategory: 'Television' },
      { slug: 'video-games', label: 'Video Games', image: `${IMG}/c/c6/Super_Pac-Man_-_Bally_Midway_Namco_arcade_cabinet.jpg/330px-Super_Pac-Man_-_Bally_Midway_Namco_arcade_cabinet.jpg`, category: 'Pop Culture', subcategory: 'Video Games' },
      { slug: 'other-pop-culture', label: 'Other Pop Culture', image: `${IMG}/4/42/Andy_Warhol_1975.jpg/330px-Andy_Warhol_1975.jpg`, category: 'Pop Culture', subcategory: 'Other Pop Culture' },
      { slug: 'geography', label: 'Geography', image: `${IMG}/9/97/The_Earth_seen_from_Apollo_17.jpg/330px-The_Earth_seen_from_Apollo_17.jpg`, category: 'Geography' },
      { slug: 'current-events', label: 'Current Events', image: `${IMG}/9/90/Printing_press_1811.jpg/330px-Printing_press_1811.jpg`, category: 'Current Events' },
      { slug: 'other-academic', label: 'Other Academic', image: `${IMG}/9/91/Bodleian_Library_John_Henry_Le_Keux_1837.jpg/330px-Bodleian_Library_John_Henry_Le_Keux_1837.jpg`, category: 'Other Academic' },
    ],
  },
]

const BY_SLUG = new Map<string, CategoryCard>()
for (const section of SECTIONS) {
  for (const card of section.cards) {
    BY_SLUG.set(card.slug, card)
  }
}

export function findCategory(slug: string): CategoryCard | undefined {
  return BY_SLUG.get(slug)
}

/** Quizbowl categories that have an Explore card, in first-seen order. */
export function categoryNames(): string[] {
  const names: string[] = []
  for (const section of SECTIONS) {
    for (const card of section.cards) {
      if (!names.includes(card.category)) names.push(card.category)
    }
  }
  return names
}

/** Subcategories and alternate subcategories filed under one category. */
export function subcategoriesOf(category: string): string[] {
  const labels: string[] = []
  for (const section of SECTIONS) {
    for (const card of section.cards) {
      if (card.category !== category) continue
      const label = card.subcategory ?? card.altSubcategory
      if (label && !labels.includes(label)) labels.push(label)
    }
  }
  return labels
}
