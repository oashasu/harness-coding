// BM25 ranking algorithm — pure TypeScript, no external deps

interface BM25Doc {
  id: string;
  tokens: string[];
}

export class BM25 {
  private docs: BM25Doc[] = [];
  private avgDl = 0;
  private df = new Map<string, number>();
  private k1 = 1.5;
  private b = 0.75;

  index(documents: { id: string; text: string }[]): void {
    this.docs = documents.map(d => ({
      id: d.id,
      tokens: this.tokenize(d.text),
    }));

    const totalLen = this.docs.reduce((s, d) => s + d.tokens.length, 0);
    this.avgDl = totalLen / this.docs.length || 1;

    this.df.clear();
    for (const doc of this.docs) {
      const seen = new Set(doc.tokens);
      for (const t of seen) {
        this.df.set(t, (this.df.get(t) || 0) + 1);
      }
    }
  }

  search(query: string, topK = 20): { id: string; score: number }[] {
    const qTokens = this.tokenize(query);
    const N = this.docs.length;

    const scores = this.docs.map(doc => {
      let score = 0;
      const tf = new Map<string, number>();
      for (const t of doc.tokens) tf.set(t, (tf.get(t) || 0) + 1);

      for (const qt of qTokens) {
        const docTf = tf.get(qt) || 0;
        const docFreq = this.df.get(qt) || 0;
        if (docTf === 0 || docFreq === 0) continue;

        const idf = Math.log((N - docFreq + 0.5) / (docFreq + 0.5) + 1);
        const tfNorm = (docTf * (this.k1 + 1)) /
          (docTf + this.k1 * (1 - this.b + this.b * (doc.tokens.length / this.avgDl)));
        score += idf * tfNorm;
      }
      return { id: doc.id, score };
    });

    return scores
      .filter(s => s.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, topK);
  }

  private tokenize(text: string): string[] {
    return text
      .toLowerCase()
      .replace(/[^\w一-鿿]/g, ' ')
      .split(/\s+/)
      .filter(t => t.length > 1);
  }
}
