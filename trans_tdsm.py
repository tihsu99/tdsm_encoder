import time, functools, torch, os, sys, random, fnmatch, psutil, argparse
from datetime import datetime
import numpy as np
import matplotlib.pyplot as plt
import torch.nn as nn
import torch.nn.functional as F
from torch.optim import Adam, RAdam
import torch.optim.lr_scheduler as lr_scheduler
from torch.utils.data import Dataset, DataLoader
from prettytable import PrettyTable
import util.display
import util.data_utils as utils
import util.sdes as sdes
import util.score_model as score_model
import util.samplers as samplers
import tqdm
from pickle import load

def check_mem():
    # Resident set size memory (non-swap physical memory process has used)
    process = psutil.Process(os.getpid())
    # Print bytes in GB
    print('Memory usage of current process 0 [GB]: ', process.memory_info().rss/(1024 * 1024 * 1024))
    return

def main():
    usage=''
    argparser = argparse.ArgumentParser(usage)
    argparser.add_argument('-o','--output',dest='output_path', help='Path to output directory', default='', type=str)
    argparser.add_argument('-s','--switches',dest='switches', help='Binary representation of switches that run: evaluation plots, training, sampling, evaluation plots', default='0000', type=str)
    argparser.add_argument('-i','--inputs',dest='inputs', help='Path to input directory', default='', type=str)
    args = argparser.parse_args()
    workingdir = args.output_path
    indir = args.inputs
    switches_ = int('0b'+args.switches,2)
    switches_str = bin(int('0b'+args.switches,2))
    trigger = 0b0001
    print(f'switches trigger: {switches_str}')
    if switches_ & trigger:
        print('input_feature_plots = ON')
    if switches_>>1 & trigger:
        print('training_switch = ON')
    if switches_>>2 & trigger:
        print('sampling_switch = ON')
    if switches_>>3 & trigger:
        print('evaluation_plots_switch = ON')

    print('torch version: ', torch.__version__)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'

    print('Running on device: ', device)
    if torch.cuda.is_available():
        print('Cuda used to build pyTorch: ',torch.version.cuda)
        print('Current device: ', torch.cuda.current_device())
        print('Cuda arch list: ', torch.cuda.get_arch_list())
    
    print('Working directory: ' , workingdir)
    
    # Useful when debugging gradient issues
    torch.autograd.set_detect_anomaly(True)
    
    padding_value = 0.0
    ### HYPERPARAMETERS ###
    train_ratio = 0.9
    batch_size = 128
    lr = 1e-3
    n_epochs = 1500
    ### SDE PARAMETERS ###
    SDE = 'VP'
    if SDE == 'VP':
        sigma_max = 20.0
        sigma_min = 0.01
    if SDE == 'VE':
        sigma_max = 20.0
        sigma_min = 0.1
    ### MODEL PARAMETERS ###
    n_feat_dim = 4
    embed_dim = 512
    hidden_dim = 128
    num_encoder_blocks = 8
    num_attn_heads = 16
    dropout_gen = 0
    # SAMPLER PARAMETERS
    sampler_steps = 100
    n_showers_2_gen = 1000

    model_params = f'''
    ### PARAMS ###
    ### SDE PARAMETERS ###
    SDE = {SDE}
    sigma/beta max. = {sigma_max}
    sigma/beta min. = {sigma_min}
    ### MODEL PARAMETERS ###
    batch_size = {batch_size}
    lr = {lr}
    n_epochs = {n_epochs}
    n_feat_dim = {n_feat_dim}
    embed_dim = {embed_dim}
    hidden_dim = {hidden_dim}
    num_encoder_blocks = {num_encoder_blocks}
    num_attn_heads = {num_attn_heads}
    dropout_gen = {dropout_gen}
    # SAMPLE PARAMETERS
    sampler_steps = {sampler_steps}
    n_showers_2_gen = {n_showers_2_gen}
    '''
    
    # Instantiate stochastic differential equation
    if SDE == 'VP':
        sde = sdes.VPSDE(beta_max=sigma_max, beta_min=sigma_min, device=device)
    if SDE == 'VE':
        sde = sdes.VESDE(sigma_max=sigma_max,device=device)
    marginal_prob_std_fn = functools.partial(sde.marginal_prob)
    diffusion_coeff_fn = functools.partial(sde.sde)

    # List of training input files
    training_file_path = os.path.join('/eos/user/j/jthomasw/tdsm_encoder/datasets/', indir)
    files_list_ = []
    print(f'Training files found in: {training_file_path}')
    
    for filename in os.listdir(training_file_path):
        if fnmatch.fnmatch(filename, 'dataset_2_padded_nentry424To564*.pt'):
            files_list_.append(os.path.join(training_file_path,filename))
    print(f'Files: {files_list_}')

    #### Input plots ####
    if switches_ & trigger:
        # Limited to n_showers_2_gen showers in for plots
        # Transformed variables
        dists_trans = util.display.plot_distribution(files_list_, nshowers_2_plot=n_showers_2_gen, padding_value=padding_value)
        entries = dists_trans[0]
        all_incident_e_trans = dists_trans[1]
        total_deposited_e_shower_trans = dists_trans[2]
        all_e_trans = dists_trans[3]
        all_x_trans = dists_trans[4]
        all_y_trans = dists_trans[5]
        all_z_trans = dists_trans[6]
        all_hit_ine_trans = dists_trans[7]
        average_x_shower_trans = dists_trans[8]
        average_y_shower_trans = dists_trans[9]

        ### 1D histograms
        fig, ax = plt.subplots(3,3, figsize=(12,12))
        print('Plot # entries')
        ax[0][0].set_ylabel('# entries')
        ax[0][0].set_xlabel('Hit entries')
        ax[0][0].hist(entries, 50, color='orange', label='Geant4')
        ax[0][0].legend(loc='upper right')

        print('Plot hit energies')
        ax[0][1].set_ylabel('# entries')
        ax[0][1].set_xlabel('Hit energy [GeV]')
        ax[0][1].hist(all_e_trans, 50, color='orange', label='Geant4')
        ax[0][1].set_yscale('log')
        ax[0][1].legend(loc='upper right')

        print('Plot hit x')
        ax[0][2].set_ylabel('# entries')
        ax[0][2].set_xlabel('Hit x position')
        ax[0][2].hist(all_x_trans, 50, color='orange', label='Geant4')
        ax[0][2].set_yscale('log')
        ax[0][2].legend(loc='upper right')

        print('Plot hit y')
        ax[1][0].set_ylabel('# entries')
        ax[1][0].set_xlabel('Hit y position')
        ax[1][0].hist(all_y_trans, 50, color='orange', label='Geant4')
        ax[1][0].set_yscale('log')
        ax[1][0].legend(loc='upper right')

        print('Plot hit z')
        ax[1][1].set_ylabel('# entries')
        ax[1][1].set_xlabel('Hit z position')
        ax[1][1].hist(all_z_trans, color='orange', label='Geant4')
        ax[1][1].set_yscale('log')
        ax[1][1].legend(loc='upper right')

        print('Plot incident energies')
        ax[1][2].set_ylabel('# entries')
        ax[1][2].set_xlabel('Incident energies [GeV]')
        ax[1][2].hist(all_incident_e_trans, 50, color='orange', label='Geant4')
        ax[1][2].set_yscale('log')
        ax[1][2].legend(loc='upper right')

        print('Plot total deposited hit energy per shower')
        ax[2][0].set_ylabel('# entries')
        ax[2][0].set_xlabel('Deposited energy [GeV]')
        ax[2][0].hist(total_deposited_e_shower_trans, 50, color='orange', label='Geant4')
        ax[2][0].set_yscale('log')
        ax[2][0].legend(loc='upper right')

        print('Plot av. X position per shower')
        ax[2][1].set_ylabel('# entries')
        ax[2][1].set_xlabel('Average X position [GeV]')
        ax[2][1].hist(average_x_shower_trans, 50, color='orange', label='Geant4')
        ax[2][1].set_yscale('log')
        ax[2][1].legend(loc='upper right')

        print('Plot av. Y position per shower')
        ax[2][2].set_ylabel('# entries')
        ax[2][2].set_xlabel('Average Y position [GeV]')
        ax[2][2].hist(average_y_shower_trans, 50, color='orange', label='Geant4')
        ax[2][2].set_yscale('log')
        ax[2][2].legend(loc='upper right')

        save_name = os.path.join(training_file_path,'input_dists_transformed.png')
        fig.savefig(save_name)

    #### Training ####
    if switches_>>1 & trigger:
        output_directory = workingdir+'/training_'+datetime.now().strftime('%Y%m%d_%H%M')+'_output/'
        print('Output directory: ', output_directory)
        if not os.path.exists(output_directory):
            print(f'Making new directory: {output_directory}')
            os.makedirs(output_directory)
        
        # Instantiate model
        model=score_model.Gen(n_feat_dim, embed_dim, hidden_dim, num_encoder_blocks, num_attn_heads, dropout_gen, marginal_prob_std=marginal_prob_std_fn)

        table = PrettyTable(['Module name', 'Parameters listed'])
        t_params = 0
        for name_ , para_ in model.named_parameters():
            if not para_.requires_grad: continue
            param = para_.numel()
            table.add_row([name_, param])
            t_params+=param
        print(table)
        print(f'Sum of trainable parameters: {t_params}')    
        
        print('model: ', model)
        if torch.cuda.device_count() > 1:
            print(f'Lets use {torch.cuda.device_count()} GPUs!')
            model = nn.DataParallel(model)

        # Optimiser needs to know model parameters for to optimise
        optimiser = RAdam(model.parameters(),lr=lr)
        scheduler = lr_scheduler.ExponentialLR(optimiser, gamma=0.99)
        
        av_training_losses_per_epoch = []
        av_testing_losses_per_epoch = []
        
        eps_ = []
        for epoch in range(0,n_epochs):
            eps_.append(epoch)
            print(f"epoch: {epoch}")
            # Create/clear per epoch variables
            cumulative_epoch_loss = 0.
            cumulative_test_epoch_loss = 0.

            file_counter = 0
            n_training_showers = 0
            n_testing_showers = 0
            training_batches_per_epoch = 0
            testing_batches_per_epoch = 0
            
            # For debugging purposes
            #files_list_ = files_list_[:1]

            # Load files
            for filename in files_list_:
                file_counter+=1

                # Rescaling now done in padding package
                custom_data = utils.cloud_dataset(filename, device=device)
                train_size = int(train_ratio * len(custom_data.data))
                test_size = len(custom_data.data) - train_size
                train_dataset, test_dataset = torch.utils.data.random_split(custom_data, [train_size, test_size])
                print(f'Size of training dataset in (file {file_counter}/{len(files_list_)}): {len(train_dataset)} showers, batch = {batch_size} showers')

                n_training_showers+=train_size
                n_testing_showers+=test_size
                # Load clouds for each epoch of data dataloaders length will be the number of batches
                shower_loader_train = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
                shower_loader_test = DataLoader(test_dataset, batch_size=batch_size, shuffle=True)

                # Accumuate number of batches per epoch
                training_batches_per_epoch += len(shower_loader_train)
                testing_batches_per_epoch += len(shower_loader_test)
                
                # Load shower batch for training
                for i, (shower_data,incident_energies) in enumerate(shower_loader_train,0):
                    
                    # Move model to device and set dtype as same as data (note torch.double works on both CPU and GPU)
                    model.to(device, shower_data.dtype)
                    model.train()
                    shower_data.to(device)
                    incident_energies.to(device)
                    if len(shower_data) < 1:
                        print('Very few hits in shower: ', len(shower_data))
                        continue

                    # Zero any gradients from previous steps
                    optimiser.zero_grad()

                    # Loss average for each batch
                    loss = score_model.loss_fn(model, shower_data, incident_energies, marginal_prob_std_fn, padding_value, device=device)
                    cumulative_epoch_loss+=float(loss)

                    # collect dL/dx for any parameters (x) which have requires_grad = True via: x.grad += dL/dx
                    loss.backward()

                    # Update value of x += -lr * x.grad
                    optimiser.step()
                
                # Testing on subset of file
                for i, (shower_data,incident_energies) in enumerate(shower_loader_test,0):
                    with torch.no_grad():
                        model.to(device, shower_data.dtype)
                        model.eval()
                        shower_data = shower_data.to(device)
                        incident_energies = incident_energies.to(device)
                        test_loss = score_model.loss_fn(model, shower_data, incident_energies, marginal_prob_std_fn, padding_value, device=device)
                        cumulative_test_epoch_loss+=float(test_loss)

            # Add the batch size just used to the total number of clouds
            # Calculate average loss per epoch
            av_training_losses_per_epoch.append(cumulative_epoch_loss/training_batches_per_epoch)
            av_testing_losses_per_epoch.append(cumulative_test_epoch_loss/testing_batches_per_epoch)
            print(f'End-of-epoch: average train loss = {av_training_losses_per_epoch}, average test loss = {av_testing_losses_per_epoch}')
            if epoch % 50 == 0:
                # Save checkpoint file after each epoch
                torch.save(model.state_dict(), output_directory+'ckpt_tmp_'+str(epoch)+'.pth')
                fig, ax = plt.subplots(ncols=1, figsize=(10,10))
                plt.title('')
                plt.ylabel('Loss')
                plt.xlabel('Epoch')
                plt.yscale('log')
                plt.plot(av_training_losses_per_epoch, label='training')
                plt.plot(av_testing_losses_per_epoch, label='testing')
                plt.legend(loc='upper right')
                plt.tight_layout()
                fig.savefig(output_directory+'loss_v_epoch.png')
            scheduler.step()
            
        torch.save(model.state_dict(), output_directory+'ckpt_tmp_'+str(epoch)+'.pth')
        print('Training losses : ', av_training_losses_per_epoch)
        print('Testing losses : ', av_testing_losses_per_epoch)
        
        # Only plot the last 80% of the epochs
        util.display.plot_loss_vs_epoch(eps_, av_training_losses_per_epoch, av_testing_losses_per_epoch, odir=output_directory)
        util.display.plot_loss_vs_epoch(eps_, av_training_losses_per_epoch, av_testing_losses_per_epoch, odir=output_directory, zoom=True)
    
    #### Sampling ####
    if switches_>>2 & trigger:    
        output_directory = workingdir+'/sampling_'+str(sampler_steps)+'samplersteps_'+datetime.now().strftime('%Y%m%d_%H%M')+'_output/'
        if not os.path.exists(output_directory):
            print(f'Making new directory: {output_directory}')
            os.makedirs(output_directory)
        
        # Load saved model
        model=score_model.Gen(n_feat_dim, embed_dim, hidden_dim, num_encoder_blocks, num_attn_heads, dropout_gen, marginal_prob_std=marginal_prob_std_fn)
        load_name = os.path.join(workingdir,'training_20230830_1430_output/ckpt_tmp_499.pth')
        model.load_state_dict(torch.load(load_name, map_location=device))
        model.to(device)


        geant_deposited_energy = []
        geant_x_pos = []
        geant_y_pos = []
        geant_ine = np.array([])
        N_geant_showers = 0

        # For diffusion plots in 'physical' feature space, add files here
        energy_trans_file = ''
        x_trans_file = ''
        y_trans_file = ''
        ine_trans_file = ''

        # Load saved pre-processor
        if ine_trans_file != '':
            print(f'energy_trans_file: {energy_trans_file}')
            scalar_ine = load(open(ine_trans_file, 'rb'))
        if energy_trans_file != '':
            scalar_e = load(open(energy_trans_file, 'rb'))
        if x_trans_file != '':
            scalar_x = load(open(x_trans_file, 'rb'))
        if y_trans_file != '':
            scalar_y = load(open(y_trans_file, 'rb'))
        
        n_files = len(files_list_)
        nshowers_per_file = [n_showers_2_gen//n_files for x in range(n_files)]
        r_ = n_showers_2_gen % nshowers_per_file[0]
        nshowers_per_file[-1] = nshowers_per_file[-1]+r_
        print(f'# showers per file: {nshowers_per_file}')
        shower_counter = 0

        # create list to store final samples
        sample_ = []
        # instantiate sampler 
        sampler = samplers.pc_sampler(sde=sde, padding_value=padding_value, snr=0.16, sampler_steps=sampler_steps, device=device, jupyternotebook=False)

        # Collect Geant4 shower information
        for file_idx in range(len(files_list_)):

            # N valid hits used for 2D PDF
            n_valid_hits_per_shower = np.array([])
            # Incident particle energy for 2D PDF
            incident_e_per_shower = np.array([])

            max_hits = -1
            file = files_list_[file_idx]
            print(f'file: {file}')
            shower_counter = 0

            # Load shower data
            custom_data = utils.cloud_dataset(file, device=device)
            point_clouds_loader = DataLoader(custom_data, batch_size=batch_size, shuffle=True)
            # Loop over batches
            for i, (shower_data, incident_energies) in enumerate(point_clouds_loader,0):
                # Copy data
                valid_event = []
                data_np = shower_data.cpu().numpy().copy()
                energy_np = incident_energies.cpu().numpy().copy()

                # Mask for padded values (padded values set to 0)
                masking = data_np[:,:,0] != padding_value

                # Loop over each shower in batch
                for j in range(len(data_np)):

                    # valid hits for shower j in batch used for GEANT plot distributions
                    valid_hits = data_np[j]

                    # real (unpadded) hit multiplicity needed for the 2D PDF later
                    n_valid_hits = data_np[j][masking[j]]

                    n_valid_hits_per_shower = np.append(n_valid_hits_per_shower, len(n_valid_hits))
                    if len(valid_hits)>max_hits:
                        max_hits = len(valid_hits)

                    incident_e_per_shower = np.append(incident_e_per_shower, energy_np[j])

                    # ONLY for plotting purposes
                    if shower_counter >= nshowers_per_file[file_idx]:
                        break
                    else:
                        shower_counter+=1

                        all_ine = energy_np[j].reshape(-1,1)

                        # Rescale the conditional input for each shower
                        if ine_trans_file != '':
                            all_ine = scalar_ine.inverse_transform(all_ine)
                        all_ine = all_ine.flatten().tolist()
                        geant_ine = np.append(geant_ine,all_ine[0])
                        
                        all_e = valid_hits[:,0].reshape(-1,1)
                        if energy_trans_file != '':
                            all_e = scalar_e.inverse_transform(all_e)
                        all_e = all_e.flatten().tolist()
                        geant_deposited_energy.append( sum( all_e ) )
                        
                        all_x = valid_hits[:,1].reshape(-1,1)
                        if x_trans_file != '':
                            all_x = scalar_x.inverse_transform(all_x)
                        all_x = all_x.flatten().tolist()
                        geant_x_pos.append( np.mean(all_x) )
                        
                        all_y = valid_hits[:,2].reshape(-1,1)
                        if y_trans_file != '':
                            all_y = scalar_y.inverse_transform(all_y)
                        all_y = all_y.flatten().tolist()
                        geant_y_pos.append( np.mean(all_y) )

                    N_geant_showers+=1
            del custom_data

            # Arrays of Nvalid hits in showers, incident energies per shower
            n_valid_hits_per_shower = np.array(n_valid_hits_per_shower)
            incident_e_per_shower = np.array(incident_e_per_shower)

            # Generate 2D pdf of incident E vs N valid hits from the training file(s)
            n_bins_prob_dist = 50
            e_vs_nhits_prob, x_bin, y_bin = samplers.get_prob_dist(incident_e_per_shower, n_valid_hits_per_shower, n_bins_prob_dist)

            # Plot 2D histogram (sanity check)
            fig0, (ax0) = plt.subplots(ncols=1, sharey=True)
            heatmap = ax0.pcolormesh(y_bin, x_bin, e_vs_nhits_prob, cmap='rainbow')
            ax0.plot(n_valid_hits_per_shower, n_valid_hits_per_shower, 'k-')
            ax0.set_xlim(n_valid_hits_per_shower.min(), n_valid_hits_per_shower.max())
            ax0.set_ylim(incident_e_per_shower.min(), incident_e_per_shower.max())
            ax0.set_xlabel('n_valid_hits_per_shower')
            ax0.set_ylabel('incident_e_per_shower')
            cbar = plt.colorbar(heatmap)
            cbar.ax.set_ylabel('PDF', rotation=270)
            ax0.set_title('histogram2d')
            ax0.grid()
            savefigname = os.path.join(output_directory,'validhits_ine_2D.png')
            fig0.savefig(savefigname)

            # Generate tensor sampled from the appropriate range of injection energies
            in_energies = torch.from_numpy(np.random.choice( incident_e_per_shower, nshowers_per_file[file_idx] ))
            if file_idx == 0:
                sampled_ine = in_energies
            else:
                sampled_ine = torch.cat([sampled_ine,in_energies])

            # Sample from 2D pdf = nhits per shower vs incident energies -> nhits and a tensor of randomly initialised hit features
            nhits, gen_hits = samplers.generate_hits(e_vs_nhits_prob, x_bin, y_bin, in_energies, 4, device=device)

            # Save
            torch.save([gen_hits, in_energies],'tmp.pt')

            # Load the showers of noise
            gen_hits = utils.cloud_dataset('tmp.pt', device=device)
            # Pad showers with values of 0
            gen_hits.padding(padding_value)
            # Load len(gen_hits_loader) number of batches each with batch_size number of showers
            gen_hits_loader = DataLoader(gen_hits, batch_size=batch_size, shuffle=False)

            # Remove noise shower file
            os.system("rm tmp.pt")

            # Create instance of sampler
            sample = []
            # Loop over each batch of noise showers
            print(f'# batches: {len(gen_hits_loader)}' )
            for i, (gen_hit, sampled_energies) in enumerate(gen_hits_loader,0):
                print(f'Generation batch {i}: showers per batch: {gen_hit.shape[0]}, max. hits per shower: {gen_hit.shape[1]}, features per hit: {gen_hit.shape[2]}, sampled_energies: {len(sampled_energies)}')    
                sys.stdout.write('\r')
                sys.stdout.write("Progress: %d/%d \n" % ((i+1), len(gen_hits_loader)))
                sys.stdout.flush()
                
                # Run reverse diffusion sampler
                generative = sampler(model, marginal_prob_std_fn, diffusion_coeff_fn, sampled_energies, gen_hit, batch_size=gen_hit.shape[0], energy_trans_file=energy_trans_file, x_trans_file=x_trans_file , y_trans_file = y_trans_file, ine_trans_file=ine_trans_file)
                
                # Create first sample or concatenate sample to sample list
                if i == 0:
                    sample = generative
                else:
                    sample = torch.cat([sample,generative])
                
                print(f'sample: {sample.shape}')
                
            sample_np = sample.cpu().numpy()

            for i in range(len(sample_np)):
                tmp_sample = sample_np[i]#[:nhits[i]]
                sample_.append(torch.tensor(tmp_sample))
        
        print(f'sample_: {len(sample_)}, sampled_ine: {len(sampled_ine)}')
        torch.save([sample_,sampled_ine], os.path.join(output_directory, 'sample.pt'))

        # Create plots of distributions evolving with diffusion steps
        print(f'Drawing diffusion plots for average hit X & Y positions')
        distributions = [
        ( ('X', 'Y'), 
        (geant_x_pos,
        geant_y_pos,
        sampler.av_x_pos_step1,
        sampler.av_y_pos_step1, 
        sampler.av_x_pos_step25,
        sampler.av_y_pos_step25,
        sampler.av_x_pos_step50,
        sampler.av_y_pos_step50,
        sampler.av_x_pos_step75,
        sampler.av_y_pos_step75,
        sampler.av_x_pos_step99,
        sampler.av_y_pos_step99) )
        ]
        util.display.make_diffusion_plot(distributions, output_directory)

        print(f'Drawing diffusion plots for average hit X positions and energies')
        distributions = [
        ( ('X', 'Total deposited energy [GeV]'), 
        (geant_x_pos,
        geant_deposited_energy,
        sampler.av_x_pos_step1,
        sampler.deposited_energy_step1, 
        sampler.av_x_pos_step25,
        sampler.deposited_energy_step25,
        sampler.av_x_pos_step50,
        sampler.deposited_energy_step50,
        sampler.av_x_pos_step75,
        sampler.deposited_energy_step75,
        sampler.av_x_pos_step99,
        sampler.deposited_energy_step99) )
        ]
        util.display.make_diffusion_plot(distributions, output_directory)
        print(f'Drawing diffusion plots for average hit energies and incident energy')
        distributions = [
        ( ('Total deposited energy', 'Incident particle energy [GeV]'), 
        (geant_deposited_energy,
        geant_ine,
        sampler.deposited_energy_step1,
        sampler.incident_e_step1, 
        sampler.deposited_energy_step25,
        sampler.incident_e_step25,
        sampler.deposited_energy_step50,
        sampler.incident_e_step50,
        sampler.deposited_energy_step75,
        sampler.incident_e_step75,
        sampler.deposited_energy_step99,
        sampler.incident_e_step99) )
        ]
        util.display.make_diffusion_plot(distributions, output_directory)

        print('Plot hit energies')
        fig, (ax1, ax2, ax3, ax4, ax5) = plt.subplots(1,5, figsize=(27,9))
        bins=np.histogram(np.hstack((geant_deposited_energy,sampler.deposited_energy_step1)), bins=50)[1]
        ax1.set_title('t=1')
        ax1.set_ylabel('# entries')
        ax1.set_xlabel('Total deposited energy [GeV]')
        ax1.hist(geant_deposited_energy, bins, alpha=0.5, color='orange', label='Geant4')
        ax1.hist(sampler.deposited_energy_step1, bins, alpha=0.5, color='blue', label='Gen')
        ax1.set_yscale('log')
        ax1.legend(loc='upper right')
        
        ax2.set_title('t=0.2')
        ax2.set_ylabel('# entries')
        ax2.set_xlabel('Total deposited energy [GeV]')
        ax2.hist(geant_deposited_energy, bins, alpha=0.5, color='orange', label='Geant4')
        ax2.hist(sampler.deposited_energy_step25, bins, alpha=0.5, color='blue', label='Gen')
        ax2.set_yscale('log')
        ax2.legend(loc='upper right')

        ax3.set_title('t=0.1')
        ax3.set_ylabel('# entries')
        ax3.set_xlabel('Total deposited energy [GeV]')
        ax3.hist(geant_deposited_energy, bins, alpha=0.5, color='orange', label='Geant4')
        ax3.hist(sampler.deposited_energy_step50, bins, alpha=0.5, color='blue', label='Gen')
        ax3.set_yscale('log')
        ax3.legend(loc='upper right')

        ax4.set_title('t=0.05')
        ax4.set_ylabel('# entries')
        ax4.set_xlabel('Total deposited energy [GeV]')
        ax4.hist(geant_deposited_energy, bins, alpha=0.5, color='orange', label='Geant4')
        ax4.hist(sampler.deposited_energy_step75, bins, alpha=0.5, color='blue', label='Gen')
        ax4.set_yscale('log')
        ax4.legend(loc='upper right')

        ax5.set_title('t=0.0')
        ax5.set_ylabel('# entries')
        ax5.set_xlabel('Total deposited energy [GeV]')
        ax5.hist(geant_deposited_energy, bins, alpha=0.5, color='orange', label='Geant4')
        ax5.hist(sampler.deposited_energy_step99, bins, alpha=0.5, color='blue', label='Gen')
        ax5.set_yscale('log')
        ax5.legend(loc='upper right')

        fig.savefig(os.path.join(output_directory,'total_deposited_energy_diffusion.png'))

    #### Evaluation plots ####
    if switches_>>3 & trigger:
        # Distributions object for generated files
        print(f'Generated inputs')
        output_directory = os.path.join(workingdir,'sampling_100samplersteps_20230829_1606_output')
        print(f'Evaluation outputs stored here: {output_directory}')
        plot_file_name = os.path.join(output_directory, 'sample.pt')
        custom_data = utils.cloud_dataset(plot_file_name,device=device)
        # when providing just cloud dataset, energy_trans_file needs to include full path
        dists_gen = util.display.plot_distribution(custom_data, nshowers_2_plot=n_showers_2_gen, padding_value=padding_value)

        entries_gen = dists_gen[0]
        all_incident_e_gen = dists_gen[1]
        total_deposited_e_shower_gen = dists_gen[2]
        all_e_gen = dists_gen[3]
        all_x_gen = dists_gen[4]
        all_y_gen = dists_gen[5]
        all_z_gen = dists_gen[6]
        all_hit_ine_gen = dists_gen[7]
        average_x_shower_gen = dists_gen[8]
        average_y_shower_gen = dists_gen[9]

        print(f'Geant4 inputs')
        # Distributions object for Geant4 files
        dists = util.display.plot_distribution(files_list_, nshowers_2_plot=n_showers_2_gen, padding_value=padding_value)

        entries = dists[0]
        all_incident_e = dists[1]
        total_deposited_e_shower = dists[2]
        all_e = dists[3]
        all_x = dists[4]
        all_y = dists[5]
        all_z = dists[6]
        all_hit_ine_geant = dists[7]
        average_x_shower_geant = dists[8]
        average_y_shower_geant = dists[9]

        print('Plot # entries')
        bins=np.histogram(np.hstack((entries,entries_gen)), bins=50)[1]
        fig, ax = plt.subplots(3,3, figsize=(12,12))
        ax[0][0].set_ylabel('# entries')
        ax[0][0].set_xlabel('Hit entries')
        ax[0][0].hist(entries, bins, alpha=0.5, color='orange', label='Geant4')
        ax[0][0].hist(entries_gen, bins, alpha=0.5, color='blue', label='Gen')
        ax[0][0].legend(loc='upper right')

        print('Plot hit energies')
        bins=np.histogram(np.hstack((all_e,all_e_gen)), bins=50)[1]
        ax[0][1].set_ylabel('# entries')
        ax[0][1].set_xlabel('Hit energy [GeV]')
        ax[0][1].hist(all_e, bins, alpha=0.5, color='orange', label='Geant4')
        ax[0][1].hist(all_e_gen, bins, alpha=0.5, color='blue', label='Gen')
        #ax[0][1].set_yscale('log')
        ax[0][1].legend(loc='upper right')

        print('Plot hit x')
        bins=np.histogram(np.hstack((all_x,all_x_gen)), bins=50)[1]
        ax[0][2].set_ylabel('# entries')
        ax[0][2].set_xlabel('Hit x position')
        ax[0][2].hist(all_x, bins, alpha=0.5, color='orange', label='Geant4')
        ax[0][2].hist(all_x_gen, bins, alpha=0.5, color='blue', label='Gen')
        #ax[0][2].set_yscale('log')
        ax[0][2].legend(loc='upper right')

        print('Plot hit y')
        bins=np.histogram(np.hstack((all_y,all_y_gen)), bins=50)[1]
        ax[1][0].set_ylabel('# entries')
        ax[1][0].set_xlabel('Hit y position')
        ax[1][0].hist(all_y, bins, alpha=0.5, color='orange', label='Geant4')
        ax[1][0].hist(all_y_gen, bins, alpha=0.5, color='blue', label='Gen')
        #ax[1][0].set_yscale('log')
        ax[1][0].legend(loc='upper right')

        print('Plot hit z')
        bins=np.histogram(np.hstack((all_z,all_z_gen)), bins=50)[1]
        ax[1][1].set_ylabel('# entries')
        ax[1][1].set_xlabel('Hit z position')
        ax[1][1].hist(all_z, bins, alpha=0.5, color='orange', label='Geant4')
        ax[1][1].hist(all_z_gen, bins, alpha=0.5, color='blue', label='Gen')
        #ax[1][1].set_yscale('log')
        ax[1][1].legend(loc='upper right')

        print('Plot incident energies')
        bins=np.histogram(np.hstack((all_incident_e,all_incident_e_gen)), bins=50)[1]
        ax[1][2].set_ylabel('# entries')
        ax[1][2].set_xlabel('Incident energies [GeV]')
        ax[1][2].hist(all_incident_e, bins, alpha=0.5, color='orange', label='Geant4')
        ax[1][2].hist(all_incident_e_gen, bins, alpha=0.5, color='blue', label='Gen')
        #ax[1][2].set_yscale('log')
        ax[1][2].legend(loc='upper right')

        print('Plot total deposited hit energy')
        bins=np.histogram(np.hstack((total_deposited_e_shower,total_deposited_e_shower_gen)), bins=50)[1]
        ax[2][0].set_ylabel('# entries')
        ax[2][0].set_xlabel('Deposited energy [GeV]')
        ax[2][0].hist(total_deposited_e_shower, bins, alpha=0.5, color='orange', label='Geant4')
        ax[2][0].hist(total_deposited_e_shower_gen, bins, alpha=0.5, color='blue', label='Gen')
        #ax[2][0].set_yscale('log')
        ax[2][0].legend(loc='upper right')

        print('Plot average hit X position')
        bins=np.histogram(np.hstack((average_x_shower_geant,average_x_shower_gen)), bins=50)[1]
        ax[2][1].set_ylabel('# entries')
        ax[2][1].set_xlabel('Average X pos.')
        ax[2][1].hist(average_x_shower_geant, bins, alpha=0.5, color='orange', label='Geant4')
        ax[2][1].hist(average_x_shower_gen, bins, alpha=0.5, color='blue', label='Gen')
        #ax[2][1].set_yscale('log')
        ax[2][1].legend(loc='upper right')

        print('Plot average hit Y position')
        bins=np.histogram(np.hstack((average_y_shower_geant,average_y_shower_gen)), bins=50)[1]
        ax[2][2].set_ylabel('# entries')
        ax[2][2].set_xlabel('Average Y pos.')
        ax[2][2].hist(average_y_shower_geant, bins, alpha=0.5, color='orange', label='Geant4')
        ax[2][2].hist(average_y_shower_gen, bins, alpha=0.5, color='blue', label='Gen')
        #ax[2][2].set_yscale('log')
        ax[2][2].legend(loc='upper right')

        fig_name = os.path.join(output_directory, 'Geant_Gen_comparison.png')
        print(f'Figure name: {fig_name}')
        fig.savefig(fig_name)


if __name__=='__main__':
    start = time.time()
    main()
    fin = time.time()
    elapsed_time = fin-start
    print('Time elapsed: {:3f}'.format(elapsed_time))
