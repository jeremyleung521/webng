import os, h5py, sys
import scipy.ndimage
import subprocess as sbpc
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import itertools as itt
import webng.analysis.utils as utils

# Hacky way to disable warnings so we can focus on important stuff
import warnings 
warnings.filterwarnings("ignore")

# TODO: Separate out the pdisting, use native code
# TODO: Hook into native code to decouple some parts like # of dimensions etc.
# we need the system.py anyway, let's use native code to read CFG file
class weAverage:
    def __init__(self, opts):
        # keep a copy of opts
        self.opts = opts
        # we need to write assignment.py sometimes
        self.pull_data_str =  "import numpy as np\n"
        self.pull_data_str += "def pull_data(n_iter, iter_group):\n"
        self.pull_data_str += "    '''\n"
        self.pull_data_str += "    This function reshapes the progress coordinate and\n"
        self.pull_data_str += "    auxiliary data for each iteration and retuns it to\n"
        self.pull_data_str += "    the tool.\n"
        self.pull_data_str += "    '''\n"
        self.pull_data_str += "    data_to_pull = np.loadtxt(\"data_to_pull.txt\") - 1\n"
        self.pull_data_str += "    d1, d2 = data_to_pull\n"
        self.pull_data_str += "    pcoord  = iter_group['pcoord'][:,:,[int(d1),int(d2)]]\n"
        self.pull_data_str += "    data = pcoord\n"    
        self.pull_data_str += "    return data\n"
        # get this in so we can import it
        sys.path.append(opts["sim_name"])
        # Once the arguments are parsed, do a few prep steps, opening h5file
        self.h5file_path = os.path.join(opts["sim_name"], "west.h5")
        self.h5file = h5py.File(self.h5file_path, 'r')
        # We can determine an iteration to pull the mapper from ourselves
        self.get_mapper(opts["mapper-iter"])
        # Set the dimensionality 
        self.set_dims(opts["dimensions"])
        # Set names if we have them
        self.set_names(opts["pcoords"])
        # Set work path
        self.work_path = opts["work-path"]
        # we want to go there
        assert os.path.isdir(self.work_path), "Work path: {} doesn't exist".format(self.work_path)
        self.curr_path = os.getcwd()
        os.chdir(self.work_path)
        # Voronoi or not
        self.voronoi = opts["plot-voronoi"]
        # Plotting energies or not?
        self.do_energy = opts["plot-energy"]
        # iterations
        self.iiter, self.fiter = self.set_iter_range(opts["first-iter"], opts["last-iter"])
        # output name
        self.outname = opts["output"]
        # data smoothing
        self.data_smoothing_level = opts["smoothing"]
        # data normalization to min/max
        self.normalize = opts["normalize"]

    def _getd(self, dic, key, default=None, required=True):
        val = dic.get(key, default)
        if required and (val is None):
            sys.exit("{} is not specified in the dictionary".format(key))
        return val
    # def _parse_args(self):
    #     parser = argparse.ArgumentParser()

    #     # Data input options
    #     parser.add_argument('-W', '--westh5',
    #                         dest='h5file_path',
    #                         default="west.h5",
    #                         help='Path to the WESTPA h5 file', 
    #                         type=str)

    #     parser.add_argument('--mapper-iter',
    #                         dest='mapper_iter', default=None,
    #                         help='Iteration to pull the bin mapper from',
    #                         type=int)

    #     parser.add_argument('--work-path',
    #                         dest='work_path', default=os.getcwd(),
    #                         help='Path to do our work in, save figs, the pdist files etc.',
    #                         type=str)

    #     parser.add_argument('--name-file',
    #                         dest='names',
    #                         default=None,
    #                         help='Text file containing the names of each dimension separated by spaces',
    #                         type=str)

    #     parser.add_argument('--do-voronoi',
    #                         dest='voronoi', action='store_true', default=False,
    #                         help='Does voronoi centers if argument given')

    #     parser.add_argument('--do-energy',
    #                         dest='do_energy', action='store_true', default=False,
    #                         help='Plot -lnP instead of probabilities')

    #     parser.add_argument('--normalize', '-n',
    #                         dest='normalize', action='store_true', default=False,
    #                         help='Normalize the data to min/max to be 0/1')

    #     parser.add_argument('--first-iter', default=None,
    #                       dest='iiter',
    #                       help='Plot data starting at iteration FIRST_ITER. '
    #                            'By default, plot data starting at the first ' 
    #                            'iteration in the specified w_pdist file. ',
    #                       type=int)

    #     parser.add_argument('--last-iter', default=None,
    #                       dest='fiter',
    #                       help='Plot data up to and including iteration '
    #                            'LAST_ITER. By default, plot data up to and '
    #                            'including the last iteration in the specified ',
    #                       type=int)

    #     # TODO Support a list of dimensions instead
    #     parser.add_argument('--dimensions', default=None,
    #                       dest='dims',
    #                       help='Number of dimensions to plot, at the moment a'
    #                             'list of dimensions is not supported',
    #                       type=int)

    #     parser.add_argument('-o', '--outname', default=None,
    #                       dest='outname',
    #                       help='Name of the output file, extension determines the format',
    #                       type=str)

    #     parser.add_argument('--smooth-data', default = None, 
    #                         dest='data_smoothing',
    #                         help='Smooth data (plotted as histogram or contour'
    #                              ' levels) using a gaussian filter with sigma='
    #                              'DATA_SMOOTHING_LEVEL.',
    #                         type=float)

    #     self.args = parser.parse_args()

    def get_mapper(self, mapper_iter):
        # Gotta fix this behavior
        if mapper_iter is None:
            mapper_iter = self.h5file.attrs['west_current_iteration'] - 1
        # Load in mapper from the iteration given/found
        print("Loading file {}, mapper from iteration {}".format(self.h5file_path, mapper_iter))
        # We have to rewrite this behavior to always have A mapper from somewhere
        # and warn the user appropriately, atm this is very shaky
        try:
            self.mapper = utils.load_mapper(self.h5file, mapper_iter)
        except:
            self.mapper = utils.load_mapper(self.h5file, mapper_iter-1)

    def set_dims(self, dims=None):
        if dims is None:
            dims = self.h5file['iterations/iter_{:08d}'.format(1)]['pcoord'].shape[2]
        self.dims = dims
        # return the dimensionality if we need to 
        return self.dims

    def set_names(self, names):
        if names is not None:
            self.names = dict( zip(range(len(names)), names) )
        else:
            # We know the dimensionality, can assume a 
            # naming scheme if we don't have one
            print("Giving default names to each dimension")
            self.names = dict( (i, str(i)) for i in range(self.dims) )

    def set_iter_range(self, iiter, fiter):
        if iiter is None:
            iiter = 0
        if fiter is None:
            fiter = self.h5file.attrs['west_current_iteration'] - 1

        return iiter, fiter 

    def setup_figure(self):
        # Setup the figure and names for each dimension
        #plt.figure(figsize=(20,20))
        plt.figure(figsize=(1.5,1.5))
        f, axarr = plt.subplots(self.dims,self.dims)
        f.subplots_adjust(hspace=0.4, wspace=0.4, bottom=0.05, left=0.05, top=0.98, right=0.98)
        return f, axarr

    def save_fig(self):
        # setup our output filename
        if self.outname is not None:
            outname = self.outname
        else:
            outname = "all_{:05d}_{:05d}.png".format(self.iiter, self.fiter)

        # save the figure
        print("Saving figure to {}".format(outname))
        plt.savefig(outname, dpi=600)
        plt.close()
        return 

    def open_pdist_file(self, fdim, sdim):
        # TODO: Rewrite so that it uses w_pdist directly and we can avoid using
        # --construct-dataset and remove the dependency on assignment.py here
        pfile = os.path.join(self.work_path, "pdist_{}_{}.h5".format(fdim, sdim))
        # for now let's just get it working
        try:
            if not os.path.isfile(pfile):
                raise IOError
            open_file = h5py.File(pfile, 'r')
            return open_file
        except IOError:
            print("Cannot open pdist file for {} vs {}, calling w_pdist".format(fdim, sdim))
            # We are assuming we don't have the file now
            # TODO: Expose # of bins somewhere, this is REALLY hacky,
            # I need to fiddle with w_pdist to fix it up
            
            # we need to have assignment.py for w_pdist to work
            # TODO: Try to make it use utils.pull data instead
            with open("assignment.py", "w") as f:
                f.write(self.pull_data_str)

            with open("data_to_pull.txt", "w") as f:
                f.write("{} {}".format(fdim, sdim))

            proc = sbpc.Popen(["w_pdist", "-W", "{}".format(self.h5file_path), 
                       "-o", "{}".format(pfile), "-b", "30", 
                       "--construct-dataset", "assignment.pull_data"])
            proc.wait()
            assert proc.returncode == 0, "w_pdist call failed, exiting"
            open_file = h5py.File(pfile, 'r')
            return open_file
            
    def run(self, ext=None):
        iiter, fiter = self.iiter, self.fiter
        if "plot-opts" in self.opts:
            plot_opts = self.opts['plot-opts']
            name_fsize = self._getd(plot_opts, "name-font-size", default=6)
            vor_lw = self._getd(plot_opts, "voronoi-lw", default=0.15)
            vor_col = self._getd(plot_opts, "voronoi-col", default=0.75)
            vor_col = str(vor_col)


        f, axarr = self.setup_figure()
        #f.suptitle("Averaged between %i - %i"%(iiter+1, fiter+1))
        # Loop over every dimension vs every other dimension
        # TODO: We could just not plot the lower triangle and 
        # save time and simplify code
        for ii,jj in itt.product(range(self.dims),range(self.dims)):
            print("Plotting {} vs {}".format((ii+1), (jj+1)))
            inv = False
            fi, fj = ii+1, jj+1

            # It's too messy to plot the spines and ticks for large dimensions
            for kw in ['top', 'right']:
                axarr[ii,jj].spines[kw].set_visible(False)
            axarr[ii,jj].tick_params(left=False, bottom=False)
        
            # Set the names if we are there
            if fi == self.dims:
                # set x label
                axarr[ii,jj].set_xlabel(self.names[jj], fontsize=name_fsize)
            if fj == 1:
                # set y label
                axarr[ii,jj].set_ylabel(self.names[ii], fontsize=name_fsize)

            # Check what type of plot we want
            if fi == fj:
                # Set equal widht height
                if self.normalize:
                    axarr[ii,jj].set(adjustable='box-forced', aspect='equal')
                # plotting the diagonal, 1D plots
                if fi != self.dims:
                    # First pull a file that contains the dimension
                    pfile = os.path.join(self.work_path, "pdist_{}_{}.h5".format(fi,self.dims))
                    datFile = self.open_pdist_file(fi, self.dims)
                    Hists = datFile['histograms'][iiter:fiter]
                    # Get average and average the other dimension
                    Hists = Hists.mean(axis=0)
                    Hists = Hists.mean(axis=1)
                else:
                    # We just need one that contains the last dimension
                    pfile = os.path.join(self.work_path, "pdist_{}_{}.h5".format(1,self.dims))
                    datFile = self.open_pdist_file(1, self.dims)
                    Hists = datFile['histograms'][iiter:fiter]
                    # Average the correct dimension here
                    Hists = Hists.mean(axis=0)
                    Hists = Hists.mean(axis=0)

                # Normalize the distribution, take -ln, zero out minimum point
                Hists = Hists/(Hists.flatten().sum())
                Hists = Hists/Hists.max()
                if self.do_energy:
                    Hists = -np.log(Hists)
                #Hists = Hists - Hists.min()

                # Calculate the x values, normalize s.t. it spans 0-1
                x_bins = datFile['binbounds_0'][...]
                x_mids = np.array([ (x_bins[i]+x_bins[i+1])/2.0 for i in range(len(x_bins)-1)] )
                if self.normalize:
                    x_mids = x_mids/x_bins.max()
          
                # Plot on the correct ax, set x limit
                if self.normalize:
                    axarr[ii,jj].set_xlim(0.0, 1.0)
                    axarr[ii,jj].set_ylim(0.0, 1.0)
                axarr[ii,jj].plot(x_mids, Hists, label="{} {}".format(fi,fj))
            else:
                # Set equal widht height
                if self.normalize:
                    axarr[ii,jj].set(adjustable='box-forced', aspect='equal')
                # Plotting off-diagonal, plotting 2D heatmaps
                if fi < fj:
                    datFile = self.open_pdist_file(fi, fj)
                    inv = False
                else:
                    datFile = self.open_pdist_file(fj, fi)
                    inv = True
        
                # Get average histograms over iterations, 
                # take -ln of the histogram after normalizing 
                # and set minimum to 0 
                Hists = datFile['histograms'][iiter:fiter]
                Hists = Hists.mean(axis=0)
                Hists = Hists/(Hists.sum())
                #Hists = -np.log(Hists)
                #Hists = Hists - Hists.min()
                # Let's remove the nans and smooth
                Hists[np.isnan(Hists)] = np.nanmax(Hists)
                if self.do_energy:
                    Hists = -np.log(Hists)
                #Hists = Hists/Hists.max()
                if self.data_smoothing_level is not None:
                    Hists = scipy.ndimage.filters.gaussian_filter(Hists,
                                      self.data_smoothing_level)
                # pcolormesh takes in transposed matrices to get 
                # the expected orientation
                e_dist = Hists.T

                # Get x/y bins, normalize them to 1 max
                x_bins = datFile['binbounds_0'][...]
                x_max = x_bins.max()
                if self.normalize:
                    if x_max != 0:
                        x_bins = x_bins/x_max
                y_bins = datFile['binbounds_1'][...]
                y_max = y_bins.max()
                if self.normalize:
                    if y_max != 0:
                        y_bins = y_bins/y_max

                # If we are at the other side of the diagonal line
                if not inv:
                    e_dist = e_dist.T
                    x_bins, y_bins = y_bins, x_bins
                
                # Set certain values to white to avoid distractions
                cmap = mpl.cm.magma_r
                cmap.set_bad(color='white')
                cmap.set_over(color='white')
                cmap.set_under(color='white')

                # Set x/y limits
                if self.normalize:
                    axarr[ii,jj].set_xlim(0.0, 1.0)
                    axarr[ii,jj].set_ylim(0.0, 1.0)
                
                # Plot the heatmap
                pcolormesh = axarr[ii,jj].pcolormesh(x_bins, y_bins,
                                    e_dist, cmap=cmap, vmin=1e-10)

                # Plot vornoi bins if asked
                if self.voronoi:
                    # Get centers from mapper
                    X = self.mapper.centers[:,ii]
                    Y = self.mapper.centers[:,jj]

                    # Normalize to 1
                    if self.normalize:
                        if not inv:
                            X = X/x_max
                            Y = Y/y_max
                        else:
                            X = X/y_max
                            Y = Y/x_max

                    # Ensure not all X/Y values are 0
                    if not ((X==0).all() or (Y==0).all()):
                        # First plot the centers
                        axarr[ii,jj].scatter(Y,X, s=0.1)

                        # Now get line segments
                        segments = utils.voronoi(Y,X)
                        lines = mpl.collections.LineCollection(segments, color=vor_col, lw=vor_lw)
                        
                        # Plot line segments
                        axarr[ii,jj].add_collection(lines)
                        axarr[ii,jj].ticklabel_format(style='sci')
        
        for i in range(0,self.dims):
            plt.setp([a.get_yticklabels() for a in axarr[:,i]], visible=False)
        for i in range(0,self.dims):
            plt.setp([a.get_xticklabels() for a in axarr[i,:]], visible=False)

        self.save_fig()
        return
