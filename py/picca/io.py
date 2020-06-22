from __future__ import print_function
import fitsio
import numpy as np
import scipy as sp
import healpy
import glob
import sys
import time
import os.path
import copy

from picca.utils import print
from picca.data import forest, delta, qso
from picca.prep_Pk1D import exp_diff, spectral_resolution, spectral_resolution_desi

## use a metadata class to simplify things
class metadata:
    pass

def read_dlas(fdla):
    """
    Read the DLA catalog from a fits file.
    ASCII or DESI files can be converted using:
        utils.eBOSS_convert_DLA()
        utils.desi_convert_DLA()
    """

    lst = ['THING_ID','Z','NHI']
    h = fitsio.FITS(fdla)
    cat = { k:h['DLACAT'][k][:] for k in lst }
    h.close()

    w = sp.argsort(cat['Z'])
    for k in cat.keys():
        cat[k] = cat[k][w]
    w = sp.argsort(cat['THING_ID'])
    for k in cat.keys():
        cat[k] = cat[k][w]

    dlas = {}
    for t in np.unique(cat['THING_ID']):
        w = t==cat['THING_ID']
        dlas[t] = [ (z,nhi) for z,nhi in zip(cat['Z'][w],cat['NHI'][w]) ]
    nb_dla = np.sum([len(d) for d in dlas.values()])

    print('\n')
    print(' In catalog: {} DLAs'.format(nb_dla) )
    print(' In catalog: {} forests have a DLA'.format(len(dlas)) )
    print('\n')

    return dlas

def read_absorbers(file_absorbers):
    f=open(file_absorbers)
    absorbers={}
    nb_absorbers = 0
    col_names=None
    for l in f:
        l = l.split()
        if len(l)==0:continue
        if l[0][0]=="#":continue
        if l[0]=="ThingID":
            col_names = l
            continue
        if l[0][0]=="-":continue
        thid = int(l[col_names.index("ThingID")])
        if thid not in absorbers:
            absorbers[thid]=[]
        lambda_absorber = float(l[col_names.index("lambda")])
        absorbers[thid].append(lambda_absorber)
        nb_absorbers += 1
    f.close()

    print("")
    print(" In catalog: {} absorbers".format(nb_absorbers) )
    print(" In catalog: {} forests have absorbers".format(len(absorbers)) )
    print("")

    return absorbers

def read_drq(drq,zmin,zmax,keep_bal,bi_max=None):
    h = fitsio.FITS(drq)

    ## Redshift
    try:
        zqso = h[1]['Z'][:]
    except:
        print("Z not found (new DRQ >= DRQ14 style), using Z_VI (DRQ <= DRQ12)")
        zqso = h[1]['Z_VI'][:]

    ## Info of the primary observation
    thid = h[1]['THING_ID'][:]
    ra = h[1]['RA'][:].astype('float64')
    dec = h[1]['DEC'][:].astype('float64')
    plate = h[1]['PLATE'][:]
    mjd = h[1]['MJD'][:]
    fid = h[1]['FIBERID'][:]

    ## Sanity
    print('')
    w = np.ones(ra.size,dtype=bool)
    print(" start               : nb object in cat = {}".format(w.sum()) )
    w &= thid>0
    print(" and thid>0          : nb object in cat = {}".format(w.sum()) )
    w &= ra!=dec
    print(" and ra!=dec         : nb object in cat = {}".format(w.sum()) )
    w &= ra!=0.
    print(" and ra!=0.          : nb object in cat = {}".format(w.sum()) )
    w &= dec!=0.
    print(" and dec!=0.         : nb object in cat = {}".format(w.sum()) )
    w &= zqso>0.
    print(" and z>0.            : nb object in cat = {}".format(w.sum()) )

    ## Redshift range
    if not zmin is None:
        w &= zqso>=zmin
        print(" and z>=zmin         : nb object in cat = {}".format(w.sum()) )
    if not zmax is None:
        w &= zqso<zmax
        print(" and z<zmax          : nb object in cat = {}".format(w.sum()) )

    ## BAL visual
    if not keep_bal and bi_max==None:
        try:
            bal_flag = h[1]['BAL_FLAG_VI'][:]
            w &= bal_flag==0
            print(" and BAL_FLAG_VI == 0  : nb object in cat = {}".format(ra[w].size) )
        except:
            print("BAL_FLAG_VI not found\n")
    ## BAL CIV
    if bi_max is not None:
        try:
            bi = h[1]['BI_CIV'][:]
            w &= bi<=bi_max
            print(" and BI_CIV<=bi_max  : nb object in cat = {}".format(ra[w].size) )
        except:
            print("--bi-max set but no BI_CIV field in h")
            sys.exit(1)
    print("")

    ra = ra[w]*sp.pi/180.
    dec = dec[w]*sp.pi/180.
    zqso = zqso[w]
    thid = thid[w]
    plate = plate[w]
    mjd = mjd[w]
    fid = fid[w]
    h.close()

    return ra,dec,zqso,thid,plate,mjd,fid


def read_zbest(zbestfiles,zmin,zmax,keep_bal,bi_max=None):
    
    #probably add a way to allow this being a list of files????
    if isinstance(zbestfiles, str):
        zbestfiles=[zbestfiles]
        numfiles=1
    else:
        numfiles=len(zbestfiles)
    print('Reading {} zbest files'.format(numfiles))

    ra_arr=[]
    dec_arr=[]
    night_arr=[]
    petal_arr=[]
    fiber_arr=[]
    tid_arr=[]
    z_arr=[]
    for zbest in zbestfiles:
        h = fitsio.FITS(zbest)

        
        try:
            h["SELECTION"]
        except OSError:
            do_selection=True
        else:
            do_selection=False
            print("already reading a catalog, no further selection besides min/max redshift")


        #selection of quasars with good redshifts only, the exact definition here should be decided, could in principle be moved to later
        spectypes=h["ZBEST"]['SPECTYPE'][:].astype(str)
        

        if do_selection:
            select=spectypes=='QSO'      #this could be done later but slower
        else:
            select=np.ones(len(spectypes),dtype=bool)


        ## Redshift
        zqso = h["ZBEST"]['Z'][:][select]
        zwarn=h["ZBEST"]['ZWARN'][:][select]    #note that zwarn is potentially not essential
        ## Info of the primary observation
        thid = h["ZBEST"]['TARGETID'][:][select]
        if len(thid)==0:
            print("no valid QSOs in file {}".format(zbest))
            continue

        tid2=h["FIBERMAP"]['TARGETID'][:]
        ra=np.zeros(len(thid), dtype='float64')
        dec=np.zeros(len(thid), dtype='float64')
        plate=np.zeros(len(thid), dtype='int64')
        night=np.zeros(len(thid), dtype='int64')
        fid=np.zeros(len(thid), dtype='int64')
        fiberstatus=[]
        cmx_target=np.zeros(len(thid), dtype='int64')
        desi_target=np.zeros(len(thid), dtype='int64')
        sv1_target=np.zeros(len(thid), dtype='int64')

        for i,tid in enumerate(thid):
            #if multiple entries in fibermap take the first here
            select2=(tid==tid2)
            ra[i] = h["FIBERMAP"]['TARGET_RA'][:][select2][0]
            dec[i] = h["FIBERMAP"]['TARGET_DEC'][:][select2][0]
            try:
                plate[i]=int('{}{}'.format(h["FIBERMAP"]['TILEID'][:][select2][0], h["FIBERMAP"]['PETAL_LOC'][:][select2][0]))
            except ValueError:
                plate[i]=int('{}{}'.format(zbest.split('-')[-2], h["FIBERMAP"]['PETAL_LOC'][:][select2][0]))   #this is to allow minisv to be read in just the same even without TILEID entries
            try:
                night[i]=int(h["FIBERMAP"]['NIGHT'][:][select2][0])
            except:
                night[i]=int(zbest.split('-')[-1].split('.')[0])
            fiberstatus.append(h["FIBERMAP"]['FIBERSTATUS'][:][select2])
            fid[i]=int( h["FIBERMAP"]['FIBER'][:][select2][0])
            try:
                cmx_target[i]=h["FIBERMAP"]['CMX_TARGET'][:][select2][0]
            except ValueError:
                pass
            try:
                desi_target[i]=h["FIBERMAP"]['DESI_TARGET'][:][select2][0]
            except ValueError:
                pass
            try:
                sv1_target[i]=h["FIBERMAP"]['SV1_DESI_TARGET'][:][select2][0]
            except ValueError:
                pass

        h.close()
        w = np.ones(ra.size,dtype=bool)

        if do_selection:
            ## Sanity
            print('')
            print("Tile {}, Petal {}".format(str(plate[0])[:-1],str(plate[0])[-1]))
            print(" start (all redrock QSOs)         : nb object in cat = {}".format(w.sum()) )
            #note that in principle we could also check for subtypes here...
            w &= (((cmx_target&(2**12))!=0) |
                    # see https://github.com/desihub/desitarget/blob/0.37.0/py/desitarget/cmx/data/cmx_targetmask.yaml
                ((desi_target&(2**2))!=0) |
                    # see https://github.com/desihub/desitarget/blob/0.37.0/py/desitarget/data/targetmask.yaml
                ((sv1_target&(2**2))!=0))
                    # see https://github.com/desihub/desitarget/blob/0.37.0/py/desitarget/sv1/data/sv1_targetmask.yaml
            print(" Targeted as QSO                  : nb object in cat = {}".format(w.sum()) )
            #the bottom selection has been done earlier already to speed up things
            #w &= spectypes == 'QSO'
            #print(" Redrock QSO                      : nb object in cat = {}".format(w.sum()) )
            
            w &= zwarn == 0
            print(" Redrock no ZWARN                 : nb object in cat = {}".format(w.sum()) )


            #checking if all fibers are fine
            w &= np.any(np.array(fiberstatus)==0,axis=1)
            print(" FIBERSTATUS==0 for any exposures : nb object in cat = {}".format(w.sum()) )

            w &= np.all(np.array(fiberstatus)==0,axis=1)
            print(" FIBERSTATUS==0 for all exposures : nb object in cat = {}".format(w.sum()) )
        else:
            print(" all objects in file              : nb object in cat = {}".format(w.sum()) )


        ## Redshift range
        if not zmin is None:
            w &= zqso>=zmin
            print(" and z>=zmin                      : nb object in cat = {}".format(w.sum()) )
        if not zmax is None:
            w &= zqso<zmax
            print(" and z<zmax                       : nb object in cat = {}".format(w.sum()) )
        ## BAL visual
        # if not keep_bal and bi_max==None:
        #     try:
        #         bal_flag = h["ZBEST"]['BAL_FLAG_VI'][:]
        #         w &= bal_flag==0
        #         print(" and BAL_FLAG_VI == 0  : nb object in cat = {}".format(ra[w].size) )
        #     except:
        #         print("BAL_FLAG_VI not found\n")
        # ## BAL CIV
        # if bi_max is not None:
        #     try:
        #         bi = h["ZBEST"]['BI_CIV'][:]
        #         w &= bi<=bi_max
        #         print(" and BI_CIV<=bi_max  : nb object in cat = {}".format(ra[w].size) )
        #     except:
        #         print("--bi-max set but no BI_CIV field in h")
        #         sys.exit(1)
        # print("")
        if not keep_bal:
            print("Note that BAL removal is not yet supported for zbest file readin!")

        ra = ra[w]*sp.pi/180.
        dec = dec[w]*sp.pi/180.
        zqso = zqso[w]
        thid = thid[w]
        plate = plate[w]
        night = night[w]
        fid = fid[w]

        ra_arr.extend(ra)
        dec_arr.extend(dec)
        fiber_arr.extend(fid)
        night_arr.extend(night)
        petal_arr.extend(plate)
        tid_arr.extend(thid)
        z_arr.extend(zqso)
    ra_arr=np.array(ra_arr)
    dec_arr=np.array(dec_arr)
    fiber_arr=np.array(fiber_arr)
    night_arr=np.array(night_arr)
    petal_arr=np.array(petal_arr)
    tid_arr=np.array(tid_arr)
    z_arr=np.array(z_arr)
    return ra_arr,dec_arr,z_arr,tid_arr,petal_arr,night_arr,fiber_arr


def read_dust_map(drq, Rv = 3.793):
    h = fitsio.FITS(drq)
    thid = h[1]['THING_ID'][:]
    ext  = h[1]['EXTINCTION'][:][:,1]/Rv
    h.close()

    return dict(zip(thid, ext))

target_mobj = 500
nside_min = 8

def read_data(in_dir,drq,mode,zmin = 2.1,zmax = 3.5,nspec=None,log=None,keep_bal=False,bi_max=None,order=1, best_obs=False, single_exp=False, pk1d=None):

    print("mode: "+mode)
    try:
        ra,dec,zqso,thid,plate,mjd,fid = read_drq(drq,zmin,zmax,keep_bal,bi_max=bi_max)
    except (ValueError,OSError,AttributeError):
        ra,dec,zqso,thid,plate,mjd,fid = read_zbest(drq,zmin,zmax,keep_bal,bi_max=bi_max)

    if nspec != None:
        ## choose them in a small number of pixels
        pixs = healpy.ang2pix(16, sp.pi / 2 - dec, ra)
        s = sp.argsort(pixs)
        ra = ra[s][:nspec]
        dec = dec[s][:nspec]
        zqso = zqso[s][:nspec]
        thid = thid[s][:nspec]
        plate = plate[s][:nspec]
        mjd = mjd[s][:nspec]
        fid = fid[s][:nspec]

    if mode == "pix":
        try:
            fin = in_dir + "/master.fits.gz"
            h = fitsio.FITS(fin)
        except IOError:
            try:
                fin = in_dir + "/master.fits"
                h = fitsio.FITS(fin)
            except IOError:
                try:
                    fin = in_dir + "/../master.fits"
                    h = fitsio.FITS(fin)
                except:
                    print("error reading master")
                    sys.exit(1)
        nside = h[1].read_header()['NSIDE']
        h.close()
        pixs = healpy.ang2pix(nside, sp.pi / 2 - dec, ra)
    elif mode in ["spec","corrected-spec","spcframe","spplate","spec-mock-1D"]:
        nside = 256
        pixs = healpy.ang2pix(nside, sp.pi / 2 - dec, ra)
        mobj = np.bincount(pixs).sum()/len(np.unique(pixs))

        ## determine nside such that there are 1000 objs per pixel on average
        print("determining nside")
        while mobj<target_mobj and nside >= nside_min:
            nside //= 2
            pixs = healpy.ang2pix(nside, sp.pi / 2 - dec, ra)
            mobj = np.bincount(pixs).sum()/len(np.unique(pixs))
        print("nside = {} -- mean #obj per pixel = {}".format(nside,mobj))
        if log is not None:
            log.write("nside = {} -- mean #obj per pixel = {}\n".format(nside,mobj))

    elif mode=="desi":
        nside = 8
        print("Found {} qsos".format(len(zqso)))
        data = read_from_desi(nside,in_dir,thid,ra,dec,zqso,plate,mjd,fid,order, pk1d=pk1d)
        return data,len(data),nside,"RING"

    elif mode=="desiminisv":
        nside = 8
        print("Found {} qsos".format(len(zqso)))
        data = read_from_desi(nside,in_dir,thid,ra,dec,zqso,plate,mjd,fid,order, pk1d=pk1d, minisv=True)
        return data,len(data),nside,"RING"

    else:
        print("I don't know mode: {}".format(mode))
        sys.exit(1)

    data ={}
    ndata = 0

    if mode=="spcframe":
        pix_data = read_from_spcframe(in_dir,thid, ra, dec, zqso, plate, mjd, fid, order, mode=mode, log=log, best_obs=best_obs, single_exp=single_exp)
        ra = [d.ra for d in pix_data]
        ra = np.array(ra)
        dec = [d.dec for d in pix_data]
        dec = np.array(dec)
        pixs = healpy.ang2pix(nside, sp.pi / 2 - dec, ra)
        for i, p in enumerate(pixs):
            if p not in data:
                data[p] = []
            data[p].append(pix_data[i])

        return data, len(pixs),nside,"RING"

    if mode in ["spplate","spec","corrected-spec"]:
        if mode == "spplate":
            pix_data = read_from_spplate(in_dir,thid, ra, dec, zqso, plate, mjd, fid, order, log=log, best_obs=best_obs)
        else:
            pix_data = read_from_spec(in_dir,thid, ra, dec, zqso, plate, mjd, fid, order, mode=mode,log=log, pk1d=pk1d, best_obs=best_obs)
        ra = [d.ra for d in pix_data]
        ra = np.array(ra)
        dec = [d.dec for d in pix_data]
        dec = np.array(dec)
        pixs = healpy.ang2pix(nside, sp.pi / 2 - dec, ra)
        for i, p in enumerate(pixs):
            if p not in data:
                data[p] = []
            data[p].append(pix_data[i])

        return data, len(pixs), nside, "RING"

    upix = np.unique(pixs)

    for i, pix in enumerate(upix):
        w = pixs == pix
        ## read all hiz qsos
        if mode == "pix":
            t0 = time.time()
            pix_data = read_from_pix(in_dir,pix,thid[w], ra[w], dec[w], zqso[w], plate[w], mjd[w], fid[w], order, log=log)
            read_time=time.time()-t0
        elif mode == "spec-mock-1D":
            t0 = time.time()
            pix_data = read_from_mock_1D(in_dir,thid[w], ra[w], dec[w], zqso[w], plate[w], mjd[w], fid[w], order, mode=mode,log=log)
            read_time=time.time()-t0
        if not pix_data is None:
            print("{} read from pix {}, {} {} in {} secs per spectrum".format(len(pix_data),pix,i,len(upix),read_time/(len(pix_data)+1e-3)))
        if not pix_data is None and len(pix_data)>0:
            data[pix] = pix_data
            ndata += len(pix_data)

    return data,ndata,nside,"RING"

def read_from_spec(in_dir,thid,ra,dec,zqso,plate,mjd,fid,order,mode,log=None,pk1d=None,best_obs=None):
    drq_dict = {t:(r,d,z) for t,r,d,z in zip(thid,ra,dec,zqso)}

    ## if using multiple observations,
    ## then replace thid, plate, mjd, fid
    ## by what's available in spAll
    if not best_obs:
        fi = glob.glob(in_dir.replace("spectra/","").replace("lite","").replace("full","")+"/spAll-*.fits")
        if len(fi) > 1:
            print("ERROR: found multiple spAll files")
            print("ERROR: try running with --bestobs option (but you will lose reobservations)")
            for f in fi:
                print("found: ",fi)
            sys.exit(1)
        if len(fi) == 0:
            print("ERROR: can't find required spAll file in {}".format(in_dir))
            print("ERROR: try runnint with --best-obs option (but you will lose reobservations)")
            sys.exit(1)

        spAll = fitsio.FITS(fi[0])
        print("INFO: reading spAll from {}".format(fi[0]))
        thid_spall = spAll[1]["THING_ID"][:]
        plate_spall = spAll[1]["PLATE"][:]
        mjd_spall = spAll[1]["MJD"][:]
        fid_spall = spAll[1]["FIBERID"][:]
        qual_spall = spAll[1]["PLATEQUALITY"][:].astype(str)
        zwarn_spall = spAll[1]["ZWARNING"][:]

        w = np.in1d(thid_spall, thid) & (qual_spall == "good")
        ## Removing spectra with the following ZWARNING bits set:
        ## SKY, LITTLE_COVERAGE, UNPLUGGED, BAD_TARGET, NODATA
        ## https://www.sdss.org/dr14/algorithms/bitmasks/#ZWARNING
        for zwarnbit in [0,1,7,8,9]:
            w &= (zwarn_spall&2**zwarnbit)==0
        print("INFO: # unique objs: ",len(thid))
        print("INFO: # spectra: ",w.sum())
        thid = thid_spall[w]
        plate = plate_spall[w]
        mjd = mjd_spall[w]
        fid = fid_spall[w]
        spAll.close()

    ## to simplify, use a list of all metadata
    allmeta = []
    ## Used to preserve original order and pass unit tests.
    t_list = []
    t_set = set()
    for t,p,m,f in zip(thid,plate,mjd,fid):
        if t not in t_set:
            t_list.append(t)
            t_set.add(t)
        r,d,z = drq_dict[t]
        meta = metadata()
        meta.thid = t
        meta.ra = r
        meta.dec = d
        meta.zqso = z
        meta.plate = p
        meta.mjd = m
        meta.fid = f
        meta.order = order
        allmeta.append(meta)

    pix_data = []
    thids = {}


    for meta in allmeta:
        t = meta.thid
        if not t in thids:
            thids[t] = []
        thids[t].append(meta)

    print("reading {} thids".format(len(thids)))

    for t in t_list:
        t_delta = None
        for meta in thids[t]:
            r,d,z,p,m,f = meta.ra,meta.dec,meta.zqso,meta.plate,meta.mjd,meta.fid
            try:
                fin = in_dir + "/{}/{}-{}-{}-{:04d}.fits".format(p,mode,p,m,f)
                h = fitsio.FITS(fin)
            except IOError:
                log.write("error reading {}\n".format(fin))
                continue
            log.write("{} read\n".format(fin))
            ll = h[1]["loglam"][:]
            fl = h[1]["flux"][:]
            iv = h[1]["ivar"][:]*(h[1]["and_mask"][:]==0)

            if pk1d is not None:
                # compute difference between exposure
                diff = exp_diff(h,ll)
                # compute spectral resolution
                wdisp =  h[1]["wdisp"][:]
                reso = spectral_resolution(wdisp,True,f,ll)
            else:
                diff = None
                reso = None
            deltas = forest(ll,fl,iv, t, r, d, z, p, m, f,order,diff=diff,reso=reso)
            if t_delta is None:
                t_delta = deltas
            else:
                t_delta += deltas
            h.close()
        if t_delta is not None:
            pix_data.append(t_delta)
    return pix_data

def read_from_mock_1D(in_dir,thid,ra,dec,zqso,plate,mjd,fid, order,mode,log=None):
    pix_data = []

    try:
        fin = in_dir
        hdu = fitsio.FITS(fin)
    except IOError:
        log.write("error reading {}\n".format(fin))

    for t,r,d,z,p,m,f in zip(thid,ra,dec,zqso,plate,mjd,fid):
        h = hdu["{}".format(t)]
        log.write("file: {} hdu {} read  \n".format(fin,h))
        lamb = h["wavelength"][:]
        ll = np.log10(lamb)
        fl = h["flux"][:]
        error =h["error"][:]
        iv = 1.0/error**2

        # compute difference between exposure
        diff = np.zeros(len(lamb))
        # compute spectral resolution
        wdisp =  h["psf"][:]
        reso = spectral_resolution(wdisp)

        # compute the mean expected flux
        f_mean_tr = h.read_header()["MEANFLUX"]
        cont = h["continuum"][:]
        mef = f_mean_tr * cont
        d = forest(ll,fl,iv, t, r, d, z, p, m, f,order, diff,reso, mef)
        pix_data.append(d)

    hdu.close()

    return pix_data


def read_from_pix(in_dir,pix,thid,ra,dec,zqso,plate,mjd,fid,order,log=None):
        try:
            fin = in_dir + "/pix_{}.fits.gz".format(pix)
            h = fitsio.FITS(fin)
        except IOError:
            try:
                fin = in_dir + "/pix_{}.fits".format(pix)
                h = fitsio.FITS(fin)
            except IOError:
                print("error reading {}".format(pix))
                return None

        ## fill log
        if log is not None:
            for t in thid:
                if t not in h[0][:]:
                    log.write("{} missing from pixel {}\n".format(t,pix))
                    print("{} missing from pixel {}".format(t,pix))

        pix_data=[]
        thid_list=list(h[0][:])
        thid2idx = {t:thid_list.index(t) for t in thid if t in thid_list}
        loglam  = h[1][:]
        flux = h[2].read()
        ivar = h[3].read()
        andmask = h[4].read()
        for (t, r, d, z, p, m, f) in zip(thid, ra, dec, zqso, plate, mjd, fid):
            try:
                idx = thid2idx[t]
            except:
                ## fill log
                if log is not None:
                    log.write("{} missing from pixel {}\n".format(t,pix))
                print("{} missing from pixel {}".format(t,pix))
                continue
            d = forest(loglam,flux[:,idx],ivar[:,idx]*(andmask[:,idx]==0), t, r, d, z, p, m, f,order)

            if log is not None:
                log.write("{} read\n".format(t))
            pix_data.append(d)
        h.close()
        return pix_data

def read_from_spcframe(in_dir, thid, ra, dec, zqso, plate, mjd, fid, order, mode=None, log=None, best_obs=False, single_exp = False):

    if not best_obs:
        print("ERROR: multiple observations not (yet) compatible with spframe option")
        print("ERROR: rerun with the --best-obs option")
        sys.exit(1)

    allmeta = []
    for t,r,d,z,p,m,f in zip(thid,ra,dec,zqso,plate,mjd,fid):
        meta = metadata()
        meta.thid = t
        meta.ra = r
        meta.dec = d
        meta.zqso = z
        meta.plate = p
        meta.mjd = m
        meta.fid = f
        meta.order = order
        allmeta.append(meta)
    platemjd = {}
    for i in range(len(thid)):
        pm = (plate[i], mjd[i])
        if not pm in platemjd:
            platemjd[pm] = []
        platemjd[pm].append(allmeta[i])

    pix_data={}
    print("reading {} plates".format(len(platemjd)))

    for pm in platemjd:
        p,m = pm
        exps = []
        spplate = in_dir+"/{0}/spPlate-{0}-{1}.fits".format(p,m)
        print("INFO: reading plate {}".format(spplate))
        h=fitsio.FITS(spplate)
        head = h[0].read_header()
        h.close()
        iexp = 1
        for c in ["B1", "B2", "R1", "R2"]:
            card = "NEXP_{}".format(c)
            if card in head:
                nexp = head["NEXP_{}".format(c)]
            else:
                continue
            for _ in range(nexp):
                str_iexp = str(iexp)
                if iexp<10:
                    str_iexp = '0'+str_iexp

                card = "EXPID"+str_iexp
                if not card in head:
                    continue

                exps.append(head["EXPID"+str_iexp][:11])
                iexp += 1

        print("INFO: found {} exposures in plate {}-{}".format(len(exps), p,m))

        if len(exps) == 0:
            continue

        exp_num = [e[3:] for e in exps]
        exp_num = np.unique(exp_num)
        sp.random.shuffle(exp_num)
        exp_num = exp_num[0]
        for exp in exps:
            if single_exp:
                if not exp_num in exp:
                    continue
            t0 = time.time()
            ## find the spectrograph number:
            spectro = int(exp[1])
            assert spectro == 1 or spectro == 2

            spcframe = fitsio.FITS(in_dir+"/{}/spCFrame-{}.fits".format(p, exp))

            flux = spcframe[0].read()
            ivar = spcframe[1].read()*(spcframe[2].read()==0)
            llam = spcframe[3].read()

            ## now convert all those fluxes into forest objects
            for meta in platemjd[pm]:
                if spectro == 1 and meta.fid > 500: continue
                if spectro == 2 and meta.fid <= 500: continue
                index =(meta.fid-1)%500
                t = meta.thid
                r = meta.ra
                d = meta.dec
                z = meta.zqso
                f = meta.fid
                order = meta.order
                d = forest(llam[index],flux[index],ivar[index], t, r, d, z, p, m, f, order)
                if t in pix_data:
                    pix_data[t] += d
                else:
                    pix_data[t] = d
                if log is not None:
                    log.write("{} read from exp {} and mjd {}\n".format(t, exp, m))
            nread = len(platemjd[pm])

            print("INFO: read {} from {} in {} per spec. Progress: {} of {} \n".format(nread, exp, (time.time()-t0)/(nread+1e-3), len(pix_data), len(thid)))
            spcframe.close()

    data = list(pix_data.values())
    return data

def read_from_spplate(in_dir, thid, ra, dec, zqso, plate, mjd, fid, order, log=None, best_obs=False):

    drq_dict = {t:(r,d,z) for t,r,d,z in zip(thid,ra,dec,zqso)}

    ## if using multiple observations,
    ## then replace thid, plate, mjd, fid
    ## by what's available in spAll

    if not best_obs:
        fi = glob.glob(in_dir+"/spAll-*.fits")
        if len(fi) > 1:
            print("ERROR: found multiple spAll files")
            print("ERROR: try running with --bestobs option (but you will lose reobservations)")
            for f in fi:
                print("found: ",fi)
            sys.exit(1)
        if len(fi) == 0:
            print("ERROR: can't find required spAll file in {}".format(in_dir))
            print("ERROR: try runnint with --best-obs option (but you will lose reobservations)")
            sys.exit(1)

        spAll = fitsio.FITS(fi[0])
        print("INFO: reading spAll from {}".format(fi[0]))
        thid_spall = spAll[1]["THING_ID"][:]
        plate_spall = spAll[1]["PLATE"][:]
        mjd_spall = spAll[1]["MJD"][:]
        fid_spall = spAll[1]["FIBERID"][:]
        qual_spall = spAll[1]["PLATEQUALITY"][:].astype(str)
        zwarn_spall = spAll[1]["ZWARNING"][:]

        w = np.in1d(thid_spall, thid)
        print("INFO: Found {} spectra with required THING_ID".format(w.sum()))
        w &= qual_spall == "good"
        print("INFO: Found {} spectra with 'good' plate".format(w.sum()))
        ## Removing spectra with the following ZWARNING bits set:
        ## SKY, LITTLE_COVERAGE, UNPLUGGED, BAD_TARGET, NODATA
        ## https://www.sdss.org/dr14/algorithms/bitmasks/#ZWARNING
        bad_zwarnbit = {0:'SKY',1:'LITTLE_COVERAGE',7:'UNPLUGGED',8:'BAD_TARGET',9:'NODATA'}
        for zwarnbit,zwarnbit_str in bad_zwarnbit.items():
            w &= (zwarn_spall&2**zwarnbit)==0
            print("INFO: Found {} spectra without {} bit set: {}".format(w.sum(), zwarnbit, zwarnbit_str))
        print("INFO: # unique objs: ",len(thid))
        print("INFO: # spectra: ",w.sum())
        thid = thid_spall[w]
        plate = plate_spall[w]
        mjd = mjd_spall[w]
        fid = fid_spall[w]
        spAll.close()

    ## to simplify, use a list of all metadata
    allmeta = []
    for t,p,m,f in zip(thid,plate,mjd,fid):
        r,d,z = drq_dict[t]
        meta = metadata()
        meta.thid = t
        meta.ra = r
        meta.dec = d
        meta.zqso = z
        meta.plate = p
        meta.mjd = m
        meta.fid = f
        meta.order = order
        allmeta.append(meta)

    pix_data = {}
    platemjd = {}
    for p,m,meta in zip(plate,mjd,allmeta):
        pm = (p,m)
        if not pm in platemjd:
            platemjd[pm] = []
        platemjd[pm].append(meta)


    print("reading {} plates".format(len(platemjd)))

    for pm in platemjd:
        p,m = pm
        spplate = in_dir + "/{0}/spPlate-{0}-{1}.fits".format(str(p).zfill(4),m)

        try:
            h = fitsio.FITS(spplate)
            head0 = h[0].read_header()
        except IOError:
            log.write("error reading {}\n".format(spplate))
            continue
        t0 = time.time()

        coeff0 = head0["COEFF0"]
        coeff1 = head0["COEFF1"]

        flux = h[0].read()
        ivar = h[1].read()*(h[2].read()==0)
        llam = coeff0 + coeff1*np.arange(flux.shape[1])

        ## now convert all those fluxes into forest objects
        for meta in platemjd[pm]:
            t = meta.thid
            r = meta.ra
            d = meta.dec
            z = meta.zqso
            f = meta.fid
            o = meta.order

            i = meta.fid-1
            d = forest(llam,flux[i],ivar[i], t, r, d, z, p, m, f, o)
            if t in pix_data:
                pix_data[t] += d
            else:
                pix_data[t] = d
            if log is not None:
                log.write("{} read from file {} and mjd {}\n".format(t, spplate, m))
        nread = len(platemjd[pm])
        print("INFO: read {} from {} in {} per spec. Progress: {} of {} \n".format(nread, os.path.basename(spplate), (time.time()-t0)/(nread+1e-3), len(pix_data), len(thid)))
        h.close()

    data = list(pix_data.values())
    return data

def read_from_desi(nside,in_dir,thid,ra,dec,zqso,plate,mjd,fid,order,pk1d=None,minisv=False):

    if not minisv:
        in_nside = int(in_dir.split('spectra-')[-1].replace('/',''))
        nest = True
        in_pixs = healpy.ang2pix(in_nside, sp.pi/2.-dec, ra,nest=nest)
        fi = sp.unique(in_pixs)
    else:
        print("I'm reading minisv")
        spectra = glob.glob(os.path.join(in_dir,"**/coadd-*.fits"),recursive=True)
        spectra = []
        plate_unique=np.unique(plate)
        for s in spectra_in:
            for p in plate_unique:
                if str(p)[:-1] in s:
                    spectra.append(s)
                    break
    data = {}
    ndata = 0

    ztable = {t:z for t,z in zip(thid,zqso)}


    for i,f in enumerate(fi):
        if not minisv:
            path = in_dir+"/"+str(int(f/100))+"/"+str(f)+"/spectra-"+str(in_nside)+"-"+str(f)+".fits"
        else:
            path=f
        print("\rread {} of {}. ndata: {}".format(i,len(fi),ndata))
        try:
            h = fitsio.FITS(path)
            if not minisv:
                tid_qsos = thid[(in_pixs==f)]
                plate_qsos = plate[(in_pixs==f)]
                mjd_qsos = mjd[(in_pixs==f)]
                fid_qsos = fid[(in_pixs==f)]
        except IOError:
            print("Error reading pix {}\n".format(f))
            continue      
        if minisv:
            petal_spec=h["FIBERMAP"]["PETAL_LOC"][:][0]
        
            if 'TILEID' in h["FIBERMAP"].get_colnames():
                tile_spec=h["FIBERMAP"]["TILEID"][:][0]
            else:
                tile_spec=fi.split('-')[-2]    #minisv tiles don't have this in the fibermap

            if 'NIGHT' in h["FIBERMAP"].get_colnames():
                night_spec=h["FIBERMAP"]["NIGHT"][:][0]
            else:
                night_spec=int(fi.split('-')[-1].split('.')[0])
        if 'TARGET_RA' in h["FIBERMAP"].get_colnames():
            ra = h["FIBERMAP"]["TARGET_RA"][:]*sp.pi/180.
            de = h["FIBERMAP"]["TARGET_DEC"][:]*sp.pi/180.
        elif 'RA_TARGET' in h["FIBERMAP"].get_colnames():
            ## TODO: These lines are for backward compatibility
            ## Should be removed at some point
            ra = h["FIBERMAP"]["RA_TARGET"][:]*sp.pi/180.
            de = h["FIBERMAP"]["DEC_TARGET"][:]*sp.pi/180.
        pixs = healpy.ang2pix(nside, sp.pi / 2 - de, ra)
        #exp = h["FIBERMAP"]["EXPID"][:]
        #night = h["FIBERMAP"]["NIGHT"][:]
        #fib = h["FIBERMAP"]["FIBER"][:]
        in_tids = h["FIBERMAP"]["TARGETID"][:]

        specData = {}
        if not minisv:
            bandnames=['B','R','Z']
        else:
            if 'brz_wavelength' in h.hdu_map.keys():
                bandnames=['BRZ']
            elif 'b_wavelength' in h.hdu_map.keys():
                bandnames=['B','R','Z']
            else:
                raise ValueError('data format not understood, neither blue spectrograph, nor BRZ coadd are part of the file (or the way they are in is not implemented)')
        for spec in bandnames:
            dic = {}
            try:
                dic['LL'] = np.log10(h['{}_WAVELENGTH'.format(spec)].read())
                dic['FL'] = h['{}_FLUX'.format(spec)].read()
                dic['IV'] = h['{}_IVAR'.format(spec)].read()*(h['{}_MASK'.format(spec)].read()==0)
                list_to_mask = ['FL','IV']

                if ('{}_DIFF_FLUX'.format(spec) in h): 
                    dic['DIFF'] = h['{}_DIFF_FLUX'.format(spec)].read()
                    w = sp.isnan(dic['FL']) | sp.isnan(dic['IV']) | sp.isnan(dic['DIFF'])
                    list_to_mask.append('DIFF')
                else:
                    w = sp.isnan(dic['FL']) | sp.isnan(dic['IV'])
                for k in list_to_mask:
                    dic[k][w] = 0.
                dic['RESO'] = h['{}_RESOLUTION'.format(spec)].read()
                specData[spec] = dic
            except OSError:
                pass
        h.close()
        if minisv:
            plate_spec = int(str(tile_spec) + str(petal_spec))
            select=(plate==plate_spec)&(mjd==night_spec)
            print('\nThis is tile {}, petal {}, night {}'.format(tile_spec,petal_spec,night_spec))
            tid_qsos = thid[select]
            plate_qsos = plate[select]
            mjd_qsos = mjd[select]
            fid_qsos = fid[select]

        for t,p,m,f in zip(tid_qsos,plate_qsos,mjd_qsos,fid_qsos):
            wt = in_tids == t
            if wt.sum()==0:
                print("\nError reading thingid {}\n".format(t))
                print("catalog thid : {}".format( tid_qsos))
                print("spectra : {}".format(spec))
                print("plate_spec : {}".format(plate_spec))
                continue

            d = None
            for tspecData in specData.values():
                iv = tspecData['IV'][wt]
                fl = (iv*tspecData['FL'][wt]).sum(axis=0)
                if("DIFF" in tspecData): diff_sp = (iv*tspecData['DIFF'][wt]).sum(axis=0)
                else : diff_sp = None
                iv = iv.sum(axis=0)
                w = iv>0.
                fl[w] /= iv[w]
                if diff_sp is not None : diff_sp[w] /= iv[w]
                if pk1d is not None:
                    reso_sum = tspecData['RESO'][wt].sum(axis=0)
                    reso_in_pixel = spectral_resolution_desi(reso_sum,tspecData['LL'])
                    if(diff_sp is not None): diff = diff_sp
                    else : diff = sp.zeros(tspecData['LL'].shape)
                else:
                    reso_in_pixel = None
                    diff = None
                    reso_sum = None
                td = forest(tspecData['LL'],fl,iv,t,ra[wt][0],de[wt][0],ztable[t],
                    p,m,f,order,diff,reso_in_pixel,reso_matrix=reso_sum)
                if d is None:
                    d = copy.deepcopy(td)
                else:
                    d += td
            if not minisv:
                pix = pixs[wt][0]
            else:
                pix = plate_spec
            if pix not in data:
                data[pix]=[]
            data[pix].append(d)
            ndata+=1

    print("found {} quasars in input files\n".format(ndata))

    return data

def read_deltas(indir,nside,lambda_abs,alpha,zref,cosmo,nspec=None,no_project=False,from_image=None):
    '''
    reads deltas from indir
    fills the fields delta.z and multiplies the weights by (1+z)^(alpha-1)/(1+zref)^(alpha-1)
    returns data,zmin_pix
    '''

    fi = []
    indir = os.path.expandvars(indir)
    if from_image is None or len(from_image)==0:
        if len(indir)>8 and indir[-8:]=='.fits.gz':
            fi += glob.glob(indir)
        elif len(indir)>5 and indir[-5:]=='.fits':
            fi += glob.glob(indir)
        else:
            fi += glob.glob(indir+'/*.fits') + glob.glob(indir+'/*.fits.gz')
    else:
        for arg in from_image:
            if len(arg)>8 and arg[-8:]=='.fits.gz':
                fi += glob.glob(arg)
            elif len(arg)>5 and arg[-5:]=='.fits':
                fi += glob.glob(arg)
            else:
                fi += glob.glob(arg+'/*.fits') + glob.glob(arg+'/*.fits.gz')
    fi = sorted(fi)

    dels = []
    ndata = 0
    for i,f in enumerate(fi):
        print("\rread {} of {} {}".format(i,len(fi),ndata))
        if from_image is None:
            hdus = fitsio.FITS(f)
            dels += [delta.from_fitsio(h) for h in hdus[1:]]
            hdus.close()
        else:
            dels += delta.from_image(f)

        ndata = len(dels)
        if not nspec is None:
            if ndata>nspec:break

    ###
    if not nspec is None:
        dels = dels[:nspec]
        ndata = len(dels)

    print("\n")

    phi = [d.ra for d in dels]
    th = [sp.pi/2.-d.dec for d in dels]
    pix = healpy.ang2pix(nside,th,phi)
    if pix.size==0:
        raise AssertionError('ERROR: No data in {}'.format(indir))

    data = {}
    zmin = 10**dels[0].ll[0]/lambda_abs-1.
    zmax = 0.
    for d,p in zip(dels,pix):
        if not p in data:
            data[p]=[]
        data[p].append(d)

        z = 10**d.ll/lambda_abs-1.
        zmin = min(zmin,z.min())
        zmax = max(zmax,z.max())
        d.z = z
        if not cosmo is None:
            d.r_comov = cosmo.r_comoving(z)
            d.rdm_comov = cosmo.dm(z)
        d.we *= ((1+z)/(1+zref))**(alpha-1)

        if not no_project:
            d.project()

    return data,ndata,zmin,zmax


def read_objects(drq,nside,zmin,zmax,alpha,zref,cosmo,keep_bal=True):
    objs = {}
    try:
        ra,dec,zqso,thid,plate,mjd,fid = read_drq(drq,zmin,zmax,keep_bal=True)
    except (ValueError,OSError,AttributeError):
        ra,dec,zqso,thid,plate,mjd,fid = read_zbest(drq,zmin,zmax,keep_bal=True)
    phi = ra
    th = sp.pi/2.-dec
    pix = healpy.ang2pix(nside,th,phi)
    if pix.size==0:
        raise AssertionError()
    print("reading qsos")

    upix = np.unique(pix)
    for i,ipix in enumerate(upix):
        print("\r{} of {}".format(i,len(upix)))
        w=pix==ipix
        objs[ipix] = [qso(t,r,d,z,p,m,f) for t,r,d,z,p,m,f in zip(thid[w],ra[w],dec[w],zqso[w],plate[w],mjd[w],fid[w])]
        for q in objs[ipix]:
            q.we = ((1.+q.zqso)/(1.+zref))**(alpha-1.)
            if not cosmo is None:
                q.r_comov = cosmo.r_comoving(q.zqso)
                q.rdm_comov = cosmo.dm(q.zqso)

    print("\n")

    return objs,zqso.min()
