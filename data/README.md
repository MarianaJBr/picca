# Published data

## DR12

### Results of J.E. Bautista et al. 2017
arXiv:1702.00176<br/>
In `Bautistaetal2017/fits/`:
 * "physical": fit results to lyman-alpha forest auto-correlation data

### Results of H. du Mas des Bourboux et al. 2017
arXiv:1708.02225<br/>
In `duMasdesBourbouxetal2017/fits/`:
 * "cross\_alone\_stdFit": standard fit results to quasar-lyman-alpha forest cross-correlation data
 * "combined\_stdFit": combined with lyman-alpha forest auto-correlation

In each folder:
 * `*.combined_fit.chisq` gives the total chi2 at best fit
 * `*..at.ap.scan.dat` gives the 2D scan of chi2 allong the
    `(alpha_perp,alpha_parallel)` parameters

## DR14

### Results of V. de Sainte Agathe et al. 2019
arXiv:1904.03400<br/>
In `deSainteAgatheetal2019/`:
 * "auto\_alone\_stdFit": fit results of the combined Lya absorption in Lya region
    auto-correlation (Lya(lya)xLya(Lya)) and  Lya absorption in Lya
    region and Lya absorption in Lyb region correlation function
    (Lya(Lya)xLya(Lyb))
 * "combined\_stdFit": combined with the cross-correlation function from Blomqvist et al. 2019

### Results of M. Blomqvist et al. 2019
arXiv:1904.03430<br/>
In `Blomqvistetal2019/`:
 * "cross\_alone\_stdFit": standard fit results to quasar-(Lya+Lyb) regions cross-correlation
    data
 * "combined\_stdFit": combined with the correlations functions from de Sainte Agathe et al. 2019.

In each folder:
 * `*.chisq` gives the total chi2 at best fit
 * `*..at.ap.scan.dat` gives the 2D scan of chi2 allong the
        `(alpha_parallel,alpha_perp)` parameters