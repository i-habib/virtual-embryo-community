# Source terms and redistribution notes

Checked **2026-09-17**. This page records what I could actually establish from the upstream sources. It is not a legal opinion, and the Virtual Embryo rules still control challenge eligibility.

## GEO-hosted molecular data

This applies to the GEO files used here for **GSE247450** and **GSE282547**, and to GEO-hosted files from **GSE197353**.

NCBI's GEO disclaimer says that NCBI places no restrictions on use or distribution of GEO data. It also says that submitters may retain patent, copyright, or other rights and that depositing data does not transfer those rights to NCBI.

Practical consequence for this repo: link to and download the upstream GEO files, record the accession and exact files, and cite the originating study. Do not describe "public on GEO" as equivalent to a blanket CC0/CC-BY grant from the study authors.

Sources:

- <https://www.ncbi.nlm.nih.gov/geo/info/disclaimer.html>
- <https://www.ncbi.nlm.nih.gov/home/about/policies/>

### GSE282547 article licence

The associated 2026 Communications Biology article is published under **CC BY-NC-ND 4.0**. That is the licence for the article and covered article material. I have not treated it as a licence for every raw/processed file deposited separately in GEO.

- Article: <https://www.nature.com/articles/s42003-026-10259-z>
- GEO: <https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE282547>

## Gene Ontology

Gene Ontology Consortium data and data products are licensed under **CC BY 4.0**. GO asks users to identify the release/date where possible and provide attribution when using or redistributing the data.

The validation manifest in this repo hashes the exact `MOUSE-mod.gaf.gz` file that was tested.

- Licence/citation policy: <https://geneontology.org/docs/go-citation-policy/>
- Current mouse GAF: <https://current.geneontology.org/annotations/gaf/MOUSE-mod.gaf.gz>

## Extended Mouse Atlas

The project page publicly provides the atlas and documents the 430,339-cell E6.5-E9.5 release. I did **not** find a dataset-specific redistribution licence on the project data page during this audit.

For that reason this repo links to the upstream release and supplies a processor, but does not vendor or redistribute the atlas. If you plan to redistribute a processed derivative, check the paper/repository terms yourself or ask the data authors.

- Project/data page: <https://marionilab.github.io/ExtendedMouseAtlas/>
- Download index: <https://bioinformatics.stemcells.cam.ac.uk/rlh60/Supplemental/ExtendedMouseAtlas/>

## sc3D convenient Figshare objects

The study's molecular data are also represented through GEO GSE197353, while the convenient reconstructed `.h5ad` objects are hosted separately on Figshare. The E9.0 object is about 12.2 GB and was not downloaded by the hosted validator.

Because the convenient object is a separately hosted file, check its Figshare record terms before redistributing that file or a derivative. The catalog does not assume that the article's licence automatically applies to the Figshare object.

- GEO: <https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE197353>
- E9.0 Figshare object: <https://figshare.com/articles/dataset/E9_0_Embryo_h5ad/21695879/1>

## Tabula Muris

Tabula Muris is retained only as a **demoted historical candidate**. The processed-object download routes documented by the old project materials and the current Open Data Registry did not reproduce from the hosted validator on 2026-09-17. I did not spend more time resolving its terms because the developing-heart atlas is much more relevant to the challenge.

- Old project data instructions: <https://github.com/czbiohub-sf/tabula-muris-vignettes/blob/master/data/README.md>
- Open Data Registry entry: <https://registry.opendata.aws/tabula-muris/>

## Challenge disclosure

Even when a source is legally reusable, the Virtual Embryo Challenge separately requires external data to obey the held-out stage/genotype restrictions and to be disclosed with enough provenance to audit what was used. Keep the `*.provenance.json` and `validation/*.json` files with your experiment records.

- Challenge rules: <https://virtualembryo.ai/challenge/rules>
